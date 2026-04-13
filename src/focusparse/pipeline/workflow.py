"""FocusWorkflow — the top-level workflows-py Workflow tying all stages together.

Phase 1 (this file): stub structure + Simple baseline runner (non-workflow) so
we can reproduce parser-bench baselines before the state machine is built.

Phase 2 (later): implement @step methods for plan / route_pages / propose_regions /
inspect / expand_context / answer / verify and wire them via typed events.

TODO(Phase 2): replace `_placeholder_run` with real workflows-py @step methods.
See https://github.com/run-llama/workflows-py for the Workflow + @step + Event API.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from focusparse._parser_bench import BenchmarkExample
from focusparse.traces.recorder import RunTrace, TrajectoryRecorder


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


class SimpleBaselineAgent:
    """Single-shot VLM baseline used for parser-bench reproducibility checks.

    TODO(Phase 1 final): prepare images per protocol, send to backend, capture
    token/USD, score with focusparse.eval.scoring.
    """

    def __init__(self, *, backend_client: Any, protocol: str) -> None:
        self.backend_client = backend_client
        self.protocol = protocol

    async def run(
        self,
        example: BenchmarkExample,
        images: list[Path],
    ) -> WorkflowResult:
        recorder = TrajectoryRecorder(example_id=example.id, question=example.question)
        # TODO: implement backend call. Placeholder keeps structure honest.
        raise NotImplementedError(
            "SimpleBaselineAgent.run — implement in Phase 1 final: "
            "call backend_client.predict(prompt=question, images=images), "
            "record one TrajectoryStep, return WorkflowResult."
        )
