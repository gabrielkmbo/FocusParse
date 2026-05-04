"""ReAct loop method — the comparator that says "any agentic loop with these tools".

This is **comparator scaffolding** for the headline-table research framework
(`plans/2026-04-29-research-driven-eval-framework.md`). It exists to fill
rows 2 of the table:

    | Method                | Datasheets | Finance |
    |-----------------------|------------|---------|
    | Base VLM              | …          | …       |
    | ReAct +2 / +4 tools   | <THIS>     | <THIS>  |
    | Agent baseline +2/+4  | …          | …       |
    | Our harness +2 / +4   | …          | …       |

The point is to isolate "is FocusParse's stage architecture doing real
work, or would any agent loop with the same tools get the same numbers?"
A clean from-scratch ReAct loop is the fairest comparator: it shares the
tools, the model, the prompt-effort budget, and the protocol; what
differs is the agentic *architecture* (loop vs FocusParse's stage
machine).

Implementation note: this is intentionally minimal. We are not optimizing
this file — see the "Development priority" note in MEMORY.md. The goal is
honest comparator numbers, not a third product.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from focusparse.models.base import ModelClient, ModelResponse
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

_DEFAULT_MAX_ITERATIONS = 6
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


_REACT_SYSTEM_PROMPT = (
    "You are a document-parsing agent answering a question about a PDF. "
    "Each turn, output STRICT JSON in one of two shapes:\n"
    '  {"thought": "...", "action": "<tool_name>", "action_input": {...}}\n'
    '  {"thought": "...", "final_answer": "...", "citations": [{"page": N, "bbox": [x0,y0,x1,y1]}]}\n'
    "Citations use normalized [0,1] bbox coordinates against the source page. "
    "BEFORE emitting `final_answer`, you MUST call at least one tool and "
    "include at least one citation pointing to the region of the page that "
    "supports your answer. If after using tools you still cannot find a "
    "supporting region, answer the literal string 'Unanswerable' with an "
    "empty citations list — do not guess. Do not add extra keys. Do not "
    "wrap in markdown other than a single ```json fence."
)


class ReActAgent:
    """LLM-driven think → act → observe loop with a configurable tool belt.

    No FocusParse stages — no planner, no router, no localizer, no
    inspector, no expander, no verifier. Just a loop over the model with
    a tool registry. The variable this comparator isolates is the
    presence/absence of the stage architecture, *not* the tool count
    (which is an independent axis controlled by `tool_set`).

    The agent's first turn receives the question + the per-example
    summary view (when the protocol provides one) + a list of available
    pages it can navigate. Subsequent turns receive the prior tool's
    summarized observation.
    """

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
        self._tools_by_name = {t.name: t for t in self.tools}

    def _system_prompt(self) -> str:
        """The system prompt this agent uses. Subclasses override for ablations.

        Default: the careful ReAct prompt with strict JSON shape +
        citation format + tool block.
        """
        return _REACT_SYSTEM_PROMPT + "\n\n" + _tool_block(self.tools)

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
        """Run the ReAct loop. Returns a `WorkflowResult` so the harness
        can aggregate ReAct cells alongside Our harness cells."""
        recorder = TrajectoryRecorder(example_id=example.id, question=example.question)
        recorder.set_plan(
            {
                "agent": "react",
                "tools": [t.name for t in self.tools],
                "max_iterations": self.max_iterations,
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

        # Conversation: a list of "user" / "agent" turns rendered into a single
        # string the LLM sees on each call. Cheap and sufficient for a
        # comparator. (We don't need a full chat-completions message history
        # — the backend client treats `prompt` as the next-user-turn input.)
        conversation: list[str] = [_initial_user_turn(example, images, pdf_path)]

        answer = ""
        citations: list[dict[str, Any]] = []
        total_tokens_in = 0
        total_tokens_out = 0
        total_usd = 0.0
        total_latency_ms = 0
        n_tool_calls = 0
        step_index = 0

        for iteration in range(self.max_iterations):
            prompt = _join_turns(conversation)
            response: ModelResponse = await self.backend_client.predict(
                prompt=prompt,
                images=images if iteration == 0 else None,
                system=self._system_prompt(),
            )
            total_tokens_in += response.tokens_in or 0
            total_tokens_out += response.tokens_out or 0
            total_usd += response.usd or 0.0
            total_latency_ms += response.latency_ms or 0

            parsed = _parse_react_turn(response.text)
            if parsed.is_final:
                answer = parsed.final_answer or ""
                citations = parsed.citations or []
                recorder.record(
                    TrajectoryStep(
                        step_index=step_index,
                        stage="react_final",
                        tier="comparator",
                        action="final_answer",
                        tool=None,
                        args={"iteration": iteration},
                        obs_summary=(response.text[:200] if response.text else None),
                        tokens_in=response.tokens_in,
                        tokens_out=response.tokens_out,
                        usd=response.usd,
                        latency_ms=response.latency_ms,
                    )
                )
                step_index += 1
                break

            # Tool-call turn. Validate, dispatch, summarize, append observation.
            obs_summary, error = await self._dispatch_tool(parsed, tool_context)
            if not error:
                n_tool_calls += 1
            recorder.record(
                TrajectoryStep(
                    step_index=step_index,
                    stage="react_step",
                    tier="comparator",
                    action="tool_call" if not error else "tool_error",
                    tool=parsed.action,
                    args={
                        "iteration": iteration,
                        "action_input": parsed.action_input or {},
                        "error": error,
                    },
                    obs_summary=obs_summary,
                    tokens_in=response.tokens_in,
                    tokens_out=response.tokens_out,
                    usd=response.usd,
                    latency_ms=response.latency_ms,
                )
            )
            step_index += 1
            conversation.append(f"agent: {response.text}".strip())
            conversation.append(f"observation: {obs_summary}")

        else:
            # Loop exhausted without `final_answer`. Treat the last
            # response.text as a best-effort answer and abstain on citations.
            logger.info(
                "ReAct loop for %s exhausted without final_answer; falling back",
                example.id,
            )
            answer = answer or _last_text_fallback(conversation) or "Unanswerable"

        # Trace schema v2 (2026-05-04): snapshot the citations the model
        # committed to as a best-effort evidence_snapshot so the per-trace
        # viewer can render them. ReAct doesn't build EvidencePackets, so
        # the summary uses citation page+bbox plus blank crops/text.
        recorder.set_evidence_snapshot(
            [
                EvidencePacketSummary(
                    packet_id=f"react_pkt_{i:03d}",
                    page=int(c.get("page", 0)) if isinstance(c, dict) else 0,
                    bbox_norm=_coerce_bbox(c.get("bbox") if isinstance(c, dict) else None),
                    provenance_tool="react_citation",
                )
                for i, c in enumerate(citations)
            ]
        )
        trace = recorder.finalize(answer=answer, citations=citations)
        telemetry = {
            "tokens_in": total_tokens_in,
            "tokens_out": total_tokens_out,
            "usd": total_usd,
            "latency_ms": total_latency_ms,
            "n_tool_calls": n_tool_calls,
            "iterations_used": step_index,
        }
        return WorkflowResult(answer=answer, citations=citations, trace=trace, telemetry=telemetry)

    async def _dispatch_tool(
        self,
        parsed: _ReActTurn,
        tool_context: dict[str, Any],
    ) -> tuple[str, str | None]:
        """Run the tool call described by `parsed`. Returns (summary, error)."""
        if not parsed.action or parsed.action not in self._tools_by_name:
            return (f"unknown tool {parsed.action!r}", "unknown_tool")
        spec = self._tools_by_name[parsed.action]
        action_input = parsed.action_input or {}
        try:
            input_model = spec.input_model.model_validate(action_input)
        except ValidationError as exc:
            return (f"input validation failed: {exc.errors()[:2]}", "validation_error")
        try:
            result = await spec.runner(input_model, **tool_context)
        except Exception as exc:  # noqa: BLE001 — comparator is best-effort
            logger.exception("Tool %s failed: %s", spec.name, exc)
            return (f"tool {spec.name} raised: {exc!s}", "tool_runtime_error")
        return (spec.summarize(result), None)


# ---------------------------------------------------------------------------
# Conversation rendering / parsing helpers
# ---------------------------------------------------------------------------


def _tool_block(tools: list[ToolSpec]) -> str:
    """Render the tool registry into a system-prompt block."""
    lines = ["Available tools:"]
    for t in tools:
        schema = t.input_model.model_json_schema()
        # Compress the schema to its top-level properties to keep prompt
        # tokens bounded. The agent gets the field names + types; the
        # description carries the use-when-to-call guidance.
        props = schema.get("properties", {})
        props_str = ", ".join(f"{k}: {v.get('type', '?')}" for k, v in list(props.items())[:8])
        lines.append(f"- {t.name}({props_str})\n    {t.description}")
    return "\n".join(lines)


_PAGE_IN_FILENAME_RE = re.compile(r"_page_(\d+)")


def _page_number_from_filename(name: str) -> int | None:
    m = _PAGE_IN_FILENAME_RE.search(name)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _initial_user_turn(
    example: BenchmarkExample,
    images: list[Path],
    pdf_path: Path | None,
) -> str:
    """Compose the agent's first user turn.

    The 2026-05-04 path-fairness fix (Phase 6 sub-plan, Track C1) enumerates
    each page-image path verbatim with its source page number so the LLM
    can use the exact strings as tool inputs instead of inventing
    `<uploaded_doc>` or `document.pdf`. Tool runners reject any other path,
    so this is correctness, not hand-holding.
    """
    parts = [f"Question: {example.question}"]
    domain = getattr(example, "domain", None)
    if domain is not None:
        parts.append(f"Domain: {str(domain).split('.')[-1].lower()}")
    if pdf_path is not None:
        parts.append(f"PDF path (use this string verbatim for `doc_path` args): {pdf_path}")
    if images:
        parts.append(
            "Available page images (use these strings verbatim for `image_path` args, "
            "and cite the matching source page number in `final_answer`):"
        )
        for img in images:
            page = _page_number_from_filename(img.name)
            page_str = f"  (page {page})" if page is not None else ""
            parts.append(f"  - {img}{page_str}")
        parts.append(
            "Tool inputs that reference doc_path or image_path MUST be one of "
            "the strings listed above; the runner will reject any other path."
        )
    return "user: " + "\n".join(parts)


def _join_turns(turns: list[str]) -> str:
    return "\n\n".join(turns)


def _last_text_fallback(turns: list[str]) -> str | None:
    for t in reversed(turns):
        if t.startswith("agent:"):
            return t[len("agent:") :].strip()
    return None


def _coerce_bbox(raw: Any) -> tuple[float, float, float, float]:
    """Best-effort 4-float bbox for a model citation. Defaults to full page."""
    if isinstance(raw, list | tuple) and len(raw) == 4:
        try:
            x0, y0, x1, y1 = (float(v) for v in raw)
            return (x0, y0, x1, y1)
        except (TypeError, ValueError):
            pass
    return (0.0, 0.0, 1.0, 1.0)


class _ReActTurn:
    """Parsed turn from the LLM."""

    __slots__ = ("is_final", "action", "action_input", "final_answer", "citations")

    def __init__(
        self,
        *,
        is_final: bool,
        action: str | None = None,
        action_input: dict[str, Any] | None = None,
        final_answer: str | None = None,
        citations: list[dict[str, Any]] | None = None,
    ) -> None:
        self.is_final = is_final
        self.action = action
        self.action_input = action_input
        self.final_answer = final_answer
        self.citations = citations


def _parse_react_turn(text: str) -> _ReActTurn:
    """Tolerant JSON parse of an LLM turn. Falls back to "treat as final
    answer" when the model emits unstructured prose."""
    if not text:
        return _ReActTurn(is_final=True, final_answer="")

    candidate = text.strip()
    fence = _JSON_FENCE_RE.search(candidate)
    if fence:
        candidate = fence.group(1)
    else:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = candidate[start : end + 1]
    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError:
        return _ReActTurn(is_final=True, final_answer=text.strip())
    if not isinstance(obj, dict):
        return _ReActTurn(is_final=True, final_answer=text.strip())

    if "final_answer" in obj:
        citations = obj.get("citations") or []
        if not isinstance(citations, list):
            citations = []
        return _ReActTurn(
            is_final=True,
            final_answer=str(obj.get("final_answer", "")),
            citations=[c for c in citations if isinstance(c, dict)],
        )

    action = obj.get("action")
    action_input = obj.get("action_input") or {}
    if not isinstance(action_input, dict):
        action_input = {}
    if isinstance(action, str):
        return _ReActTurn(is_final=False, action=action, action_input=action_input)
    # Malformed — treat as final answer with whatever text is there.
    return _ReActTurn(is_final=True, final_answer=text.strip())
