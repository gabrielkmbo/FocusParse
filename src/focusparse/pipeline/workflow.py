"""FocusWorkflow — the top-level workflows-py Workflow tying all stages together.

Phase 1 (this file): stub structure + Simple baseline runner (non-workflow) so
we can reproduce parser-bench baselines before the state machine is built.

Phase 2 (later): implement @step methods for plan / route_pages / propose_regions /
inspect / expand_context / answer / verify and wire them via typed events.

TODO(Phase 2): replace `_placeholder_run` with real workflows-py @step methods.
See https://github.com/run-llama/workflows-py for the Workflow + @step + Event API.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from focusparse.models.base import ModelClient, ModelResponse
from focusparse.traces.recorder import RunTrace, TrajectoryRecorder, TrajectoryStep

if TYPE_CHECKING:
    from focusparse._parser_bench import BenchmarkExample


@dataclass
class WorkflowResult:
    answer: str
    citations: list[dict[str, Any]]
    trace: RunTrace
    telemetry: dict[str, Any]


class FocusWorkflow:
    """The 6-stage lens workflow. Phase 2 target.

    Usage (post-Phase-2):
        workflow = FocusWorkflow(config=..., tier_router=..., cache=..., tools=...)
        result = await workflow.run(example, protocol="focus")
    """

    def __init__(self, *, config: Any, tier_router: Any, cache: Any, tools: Any) -> None:
        self.config = config
        self.tier_router = tier_router
        self.cache = cache
        self.tools = tools

    async def run(
        self,
        example: BenchmarkExample,
        *,
        protocol: str = "focus",
        output_dir: Path | None = None,
    ) -> WorkflowResult:
        raise NotImplementedError("FocusWorkflow.run — wire in Phase 2")


# ---------------------------------------------------------------------------
# SimpleBaselineAgent
# ---------------------------------------------------------------------------

_SIMPLE_SYSTEM_PROMPT = (
    "You are answering a question about a document using the provided page image(s). "
    "Return strict JSON with keys `answer` and `citations`. "
    "`answer` is the answer string (or the literal word 'Unanswerable'). "
    '`citations` is a list of objects `{"page": <int>, "bbox": [x0, y0, x1, y1]}` '
    "with normalized [0,1] coordinates pointing to the region that supports the answer. "
    "If no region applies, return an empty citations list. Do not add extra keys."
)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


class SimpleBaselineAgent:
    """Single-shot VLM baseline used for parser-bench reproducibility checks.

    Protocol handling is the caller's job — `images` is already prepared for
    `full_doc` / `oracle_page` / `oracle_crop`. The agent does one VLM call
    and records a single `TrajectoryStep`.
    """

    def __init__(self, *, backend_client: ModelClient, protocol: str) -> None:
        self.backend_client = backend_client
        self.protocol = protocol

    async def run(
        self,
        example: BenchmarkExample,
        images: list[Path],
    ) -> WorkflowResult:
        recorder = TrajectoryRecorder(example_id=example.id, question=example.question)
        recorder.set_plan({"agent": "simple", "protocol": self.protocol, "n_images": len(images)})

        prompt = f"Question: {example.question}"
        response: ModelResponse = await self.backend_client.predict(
            prompt=prompt,
            images=images,
            system=_SIMPLE_SYSTEM_PROMPT,
        )

        answer, citations = _parse_simple_response(response.text)

        recorder.record(
            TrajectoryStep(
                step_index=0,
                stage="simple_answer",
                tier="baseline",
                action="llm_call",
                tool=None,
                args={"protocol": self.protocol, "n_images": len(images)},
                obs_summary=(response.text[:200] if response.text else None),
                tokens_in=response.tokens_in,
                tokens_out=response.tokens_out,
                latency_ms=response.latency_ms,
                usd=response.usd,
            )
        )
        trace = recorder.finalize(answer=answer, citations=citations)

        telemetry = {
            "tokens_in": response.tokens_in,
            "tokens_out": response.tokens_out,
            "usd": response.usd,
            "latency_ms": response.latency_ms,
            "raw_response_len": len(response.text or ""),
        }
        return WorkflowResult(answer=answer, citations=citations, trace=trace, telemetry=telemetry)


def _parse_simple_response(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Extract (answer, citations) from a model response.

    Tolerates: bare JSON, JSON in a ```json fence, or free text (fallback = raw
    text as answer, empty citations). Never raises — a broken response yields
    answer=text, citations=[].
    """
    if not text:
        return "", []

    candidate = text.strip()
    fence = _JSON_FENCE_RE.search(candidate)
    if fence:
        candidate = fence.group(1)
    else:
        # Try to find the first top-level {...} block.
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = candidate[start : end + 1]

    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError:
        return text.strip(), []

    if not isinstance(obj, dict):
        return text.strip(), []

    answer = obj.get("answer", "")
    if not isinstance(answer, str):
        answer = str(answer)

    raw_citations = obj.get("citations", []) or []
    citations: list[dict[str, Any]] = []
    for c in raw_citations:
        if not isinstance(c, dict):
            continue
        page = c.get("page")
        bbox = c.get("bbox")
        if not isinstance(page, int):
            try:
                page = int(page)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
        if not (isinstance(bbox, list) and len(bbox) == 4):
            continue
        try:
            bbox_f = [float(x) for x in bbox]
        except (TypeError, ValueError):
            continue
        citations.append({"page": page, "bbox": bbox_f})

    return answer, citations
