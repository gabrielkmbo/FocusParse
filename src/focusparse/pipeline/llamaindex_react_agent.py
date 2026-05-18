"""Official LlamaIndex ReAct comparator.

This is the primary trusted ReAct row for the related-work experiment
program. Unlike `react_agent.py`, which is a repo-native ReAct ablation,
this adapter uses LlamaIndex's official `ReActAgent` workflow and
`FunctionTool` API while preserving FocusParse's model client, tool registry,
artifact shape, and scoring contract.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import PrivateAttr, ValidationError

from focusparse.models.base import ModelClient, ModelResponse
from focusparse.pipeline.react_agent import _coerce_bbox, _initial_user_turn
from focusparse.pipeline.workflow import WorkflowResult
from focusparse.tools import ToolSpec
from focusparse.traces.recorder import (
    EvidencePacketSummary,
    TrajectoryRecorder,
    TrajectoryStep,
)

if TYPE_CHECKING:
    from focusparse._parser_bench import BenchmarkExample

logger = logging.getLogger(__name__)

_DEFAULT_MAX_ITERATIONS = 10
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)

_LLAMAINDEX_REACT_API = "llama_index.core.agent.workflow.ReActAgent"
_LLAMAINDEX_TOOL_API = "llama_index.core.tools.FunctionTool"

_LLAMAINDEX_REACT_SYSTEM_HEADER = """
You are a document-parsing ReAct agent answering a question about a PDF.

## Tools

You have access to the following tools:
{tool_desc}

## Output Format

Use LlamaIndex ReAct format exactly.

To call a tool:

Thought: <what you are thinking>
Action: <tool name, one of {tool_names}>
Action Input: <valid JSON object of tool kwargs>

When you have enough evidence to answer:

Thought: I can answer without using any more tools.
Answer: {{"final_answer": "...", "citations": [{{"page": N, "bbox": [x0, y0, x1, y1]}}]}}

Citations use normalized [0,1] bbox coordinates against the source page.
Before emitting Answer, you MUST call at least one tool and include at least
one citation pointing to the region of the page that supports your answer.
If after using tools you still cannot find a supporting region, answer with
{{"final_answer": "Unanswerable", "citations": []}}.

Do not surround responses with markdown code fences. Action Input must be
valid JSON, not Python dict syntax.

## Current Conversation

Below is the current conversation consisting of interleaving human, assistant,
and observation messages.
""".strip()


def _llamaindex_custom_llm_base():
    try:
        from llama_index.core.llms import CustomLLM
    except Exception as exc:  # pragma: no cover - dependency failure path
        raise RuntimeError(
            "Official LlamaIndex ReAct is unavailable: could not import "
            "llama_index.core.llms.CustomLLM"
        ) from exc
    return CustomLLM


@dataclass
class _LlamaIndexCall:
    prompt: str
    system: str | None
    images: list[Path] | None
    response: ModelResponse


class _FocusParseLlamaIndexLLM(_llamaindex_custom_llm_base()):
    """LlamaIndex LLM wrapper backed by FocusParse's `ModelClient`.

    LlamaIndex drives the ReAct loop through `achat()`. This wrapper renders
    the chat messages into the same prompt/system split used elsewhere in
    FocusParse and attaches the protocol images on the first model call only.
    """

    _backend_client: ModelClient = PrivateAttr()
    _images: list[Path] = PrivateAttr(default_factory=list)
    _calls: list[_LlamaIndexCall] = PrivateAttr(default_factory=list)

    def __init__(self, *, backend_client: ModelClient, images: list[Path]) -> None:
        from llama_index.core.callbacks import CallbackManager

        super().__init__(callback_manager=CallbackManager([]))
        self._backend_client = backend_client
        self._images = list(images)
        self._calls = []

    @classmethod
    def class_name(cls) -> str:
        return "focusparse_model_client_llm"

    @property
    def calls(self) -> list[_LlamaIndexCall]:
        return list(self._calls)

    @property
    def metadata(self):
        from llama_index.core.llms import LLMMetadata

        return LLMMetadata(is_chat_model=True, model_name="focusparse-model-client")

    async def achat(self, messages: Sequence[Any], **kwargs: Any):
        from llama_index.core.llms import ChatMessage, ChatResponse, MessageRole

        system, prompt = _render_llamaindex_messages(messages)
        images = self._images if not self._calls and self._images else None
        response = await self._backend_client.predict(
            prompt=prompt,
            images=images,
            system=system,
            max_tokens=kwargs.get("max_tokens"),
        )
        self._calls.append(
            _LlamaIndexCall(prompt=prompt, system=system, images=images, response=response)
        )
        return ChatResponse(
            message=ChatMessage(role=MessageRole.ASSISTANT, content=response.text),
            raw=response.model_dump(),
        )

    async def acomplete(self, prompt: str, formatted: bool = False, **kwargs: Any):
        from llama_index.core.llms import CompletionResponse

        images = self._images if not self._calls and self._images else None
        response = await self._backend_client.predict(
            prompt=prompt,
            images=images,
            system=None,
            max_tokens=kwargs.get("max_tokens"),
        )
        self._calls.append(
            _LlamaIndexCall(prompt=prompt, system=None, images=images, response=response)
        )
        return CompletionResponse(text=response.text, raw=response.model_dump())

    def chat(self, messages: Sequence[Any], **kwargs: Any):
        raise RuntimeError("FocusParse LlamaIndex LLM supports async chat only")

    def complete(self, prompt: str, formatted: bool = False, **kwargs: Any):
        raise RuntimeError("FocusParse LlamaIndex LLM supports async completion only")

    def stream_chat(self, messages: Sequence[Any], **kwargs: Any):
        raise RuntimeError("FocusParse LlamaIndex LLM streaming is disabled")

    def stream_complete(self, prompt: str, formatted: bool = False, **kwargs: Any):
        raise RuntimeError("FocusParse LlamaIndex LLM streaming is disabled")

    async def astream_chat(self, messages: Sequence[Any], **kwargs: Any):
        response = await self.achat(messages, **kwargs)

        async def _gen():
            yield response

        return _gen()

    async def astream_complete(self, prompt: str, formatted: bool = False, **kwargs: Any):
        response = await self.acomplete(prompt, formatted=formatted, **kwargs)

        async def _gen():
            yield response

        return _gen()


class LlamaIndexReActAgent:
    """Official LlamaIndex ReAct comparator over FocusParse tools."""

    def __init__(
        self,
        *,
        backend_client: ModelClient,
        tools: list[ToolSpec],
        max_iterations: int = _DEFAULT_MAX_ITERATIONS,
    ) -> None:
        self.backend_client = backend_client
        self.tools = list(tools)
        self.max_iterations = int(max_iterations)

    @property
    def implementation_metadata(self) -> dict[str, Any]:
        return {
            "name": "official_llamaindex_react",
            "framework": "llama-index",
            "framework_version": _llamaindex_version(),
            "agent_api": _LLAMAINDEX_REACT_API,
            "tool_api": _LLAMAINDEX_TOOL_API,
            "adapter": "focusparse.pipeline.llamaindex_react_agent.LlamaIndexReActAgent",
            "fallback": None,
        }

    async def run(
        self,
        example: BenchmarkExample,
        images: list[Path],
        *,
        pdf_path: Path | None = None,
        crop_cache_dir: Path | None = None,
        text_layer_cache_dir: Path | None = None,
        layout_endpoint_url: str | None = None,
        hf_token: str | None = None,
        layout_cache_dir: Path | None = None,
    ) -> WorkflowResult:
        """Run the official LlamaIndex ReAct workflow and return WorkflowResult."""

        recorder = TrajectoryRecorder(example_id=example.id, question=example.question)
        recorder.set_plan(
            {
                "agent": "llamaindex_react",
                "official_llamaindex_react": True,
                "implementation": self.implementation_metadata,
                "tools": [t.name for t in self.tools],
                "max_iterations": self.max_iterations,
                "early_stopping_method": "generate",
                "n_images": len(images),
            }
        )

        tool_context = {
            "cache_dir": crop_cache_dir,
            "crop_cache_dir": crop_cache_dir,
            "text_layer_cache_dir": text_layer_cache_dir,
            "image_cache_dir": crop_cache_dir,
            "layout_endpoint_url": layout_endpoint_url,
            "hf_token": hf_token,
            "layout_cache_dir": layout_cache_dir,
        }
        llm = _FocusParseLlamaIndexLLM(backend_client=self.backend_client, images=images)
        agent = _build_llamaindex_react_agent(
            llm=llm,
            tools=[_to_llamaindex_tool(t, tool_context) for t in self.tools],
        )

        events: list[Any] = []
        user_msg = _initial_user_turn(example, images, pdf_path)
        handler = agent.run(
            user_msg=user_msg,
            max_iterations=self.max_iterations,
            early_stopping_method="generate",
        )
        async for event in handler.stream_events():
            events.append(event)
        output = await handler

        final_text = _output_text(output)
        answer, citations = _parse_final_answer_payload(final_text)
        _record_llamaindex_events(recorder, events, llm.calls)

        recorder.set_evidence_snapshot(
            [
                EvidencePacketSummary(
                    packet_id=f"llamaindex_react_pkt_{i:03d}",
                    page=int(c.get("page", 0)) if isinstance(c, dict) else 0,
                    bbox_norm=_coerce_bbox(c.get("bbox") if isinstance(c, dict) else None),
                    provenance_tool="llamaindex_react_citation",
                )
                for i, c in enumerate(citations)
            ]
        )
        trace = recorder.finalize(answer=answer, citations=citations)
        telemetry = _telemetry_from_calls(llm.calls)
        telemetry.update(
            {
                "n_tool_calls": _successful_tool_call_count(events),
                "iterations_used": len(llm.calls),
                "official_llamaindex_react": True,
                "llamaindex_api": _LLAMAINDEX_REACT_API,
                "llamaindex_version": _llamaindex_version(),
            }
        )
        return WorkflowResult(answer=answer, citations=citations, trace=trace, telemetry=telemetry)


def _build_llamaindex_react_agent(*, llm: Any, tools: list[Any]):
    try:
        from llama_index.core.agent.react.formatter import ReActChatFormatter
        from llama_index.core.agent.workflow import ReActAgent as LlamaIndexReActAgent
    except Exception as exc:  # pragma: no cover - dependency failure path
        raise RuntimeError(
            "Official LlamaIndex ReAct is unavailable: expected "
            "llama_index.core.agent.workflow.ReActAgent and "
            "llama_index.core.agent.react.formatter.ReActChatFormatter"
        ) from exc

    return LlamaIndexReActAgent(
        name="focusparse_llamaindex_react",
        description="Official LlamaIndex ReAct comparator for parser-bench.",
        llm=llm,
        tools=tools,
        formatter=ReActChatFormatter.from_defaults(system_header=_LLAMAINDEX_REACT_SYSTEM_HEADER),
        streaming=False,
        verbose=False,
    )


def _to_llamaindex_tool(spec: ToolSpec, tool_context: dict[str, Any]) -> Any:
    try:
        from llama_index.core.tools import FunctionTool
    except Exception as exc:  # pragma: no cover - dependency failure path
        raise RuntimeError(
            "Official LlamaIndex tool API is unavailable: expected "
            "llama_index.core.tools.FunctionTool"
        ) from exc

    async def _invoke(**kwargs: Any) -> Any:
        try:
            input_model = spec.input_model.model_validate(kwargs)
        except ValidationError as exc:
            raise ValueError(f"{spec.name} input validation failed: {exc.errors()[:2]}") from exc
        return await spec.runner(input_model, **tool_context)

    return FunctionTool.from_defaults(
        async_fn=_invoke,
        name=spec.name,
        description=spec.description,
        fn_schema=spec.input_model,
        callback=spec.summarize,
    )


def _render_llamaindex_messages(messages: Sequence[Any]) -> tuple[str | None, str]:
    system_parts: list[str] = []
    prompt_parts: list[str] = []
    for msg in messages:
        role = str(getattr(msg, "role", "")).split(".")[-1].lower()
        content = _message_content(msg)
        if role == "system":
            system_parts.append(content)
        else:
            prompt_parts.append(f"{role or 'message'}: {content}")
    return ("\n\n".join(system_parts) or None, "\n\n".join(prompt_parts))


def _message_content(msg: Any) -> str:
    content = getattr(msg, "content", None)
    if content is not None:
        return str(content)
    blocks = getattr(msg, "blocks", None) or []
    texts: list[str] = []
    for block in blocks:
        text = getattr(block, "text", None)
        if text is not None:
            texts.append(str(text))
    return "\n".join(texts)


def _output_text(output: Any) -> str:
    response = getattr(output, "response", None)
    if response is None:
        return str(output or "")
    return _message_content(response).strip()


def _parse_final_answer_payload(text: str) -> tuple[str, list[dict[str, Any]]]:
    raw = text.strip()
    if raw.startswith("Answer:"):
        raw = raw[len("Answer:") :].strip()
    payload = _extract_json_object(raw)
    if isinstance(payload, dict) and "final_answer" in payload:
        citations = payload.get("citations")
        return str(payload.get("final_answer") or ""), (
            citations if isinstance(citations, list) else []
        )
    return (raw or "Unanswerable", [])


def _extract_json_object(text: str) -> Any:
    fenced = _JSON_FENCE_RE.search(text)
    candidate = fenced.group(1) if fenced else text
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    start = candidate.find("{")
    if start < 0:
        return None
    try:
        payload, _ = json.JSONDecoder().raw_decode(candidate[start:])
        return payload
    except json.JSONDecodeError:
        return None


def _record_llamaindex_events(
    recorder: TrajectoryRecorder,
    events: list[Any],
    calls: list[_LlamaIndexCall],
) -> None:
    call_idx = 0
    step_index = 0
    for event in events:
        name = event.__class__.__name__
        if name == "AgentOutput":
            call = calls[call_idx] if call_idx < len(calls) else None
            call_idx += 1
            tool_calls = [
                {
                    "tool_name": getattr(t, "tool_name", None),
                    "tool_kwargs": getattr(t, "tool_kwargs", None),
                }
                for t in (getattr(event, "tool_calls", None) or [])
            ]
            recorder.record(
                TrajectoryStep(
                    step_index=step_index,
                    stage="llamaindex_react",
                    tier="comparator",
                    action="llm_call" if tool_calls else "final_answer",
                    tool=None,
                    args={
                        "official_llamaindex_react": True,
                        "tool_calls": tool_calls,
                    },
                    obs_summary=_output_text(event)[:300],
                    tokens_in=call.response.tokens_in if call else 0,
                    tokens_out=call.response.tokens_out if call else 0,
                    usd=call.response.usd if call else None,
                    latency_ms=call.response.latency_ms if call else 0,
                )
            )
            step_index += 1
        elif name == "ToolCallResult":
            tool_output = getattr(event, "tool_output", None)
            is_error = bool(getattr(tool_output, "is_error", False))
            recorder.record(
                TrajectoryStep(
                    step_index=step_index,
                    stage="llamaindex_react_tool",
                    tier="comparator",
                    action="tool_error" if is_error else "tool_call",
                    tool=getattr(event, "tool_name", None),
                    args={
                        "tool_kwargs": getattr(event, "tool_kwargs", None) or {},
                        "is_error": is_error,
                    },
                    obs_summary=str(getattr(tool_output, "content", "") or "")[:300],
                )
            )
            step_index += 1


def _telemetry_from_calls(calls: list[_LlamaIndexCall]) -> dict[str, Any]:
    return {
        "tokens_in": sum(c.response.tokens_in or 0 for c in calls),
        "tokens_out": sum(c.response.tokens_out or 0 for c in calls),
        "usd": sum(c.response.usd or 0.0 for c in calls),
        "latency_ms": sum(c.response.latency_ms or 0 for c in calls),
    }


def _successful_tool_call_count(events: list[Any]) -> int:
    total = 0
    for event in events:
        if event.__class__.__name__ != "ToolCallResult":
            continue
        tool_output = getattr(event, "tool_output", None)
        if not bool(getattr(tool_output, "is_error", False)):
            total += 1
    return total


def _llamaindex_version() -> str | None:
    try:
        return version("llama-index-core")
    except PackageNotFoundError:
        return None
