"""In-workflow trajectory capture.

Every pipeline @step records a `TrajectoryStep`. At run end, `RunTrace` is
serialized to JSONL for later SFT (AgenticOCR recipe) or GRPO.

Schema contract: changes to TrajectoryStep fields require bumping
`traces.schema_version` in `configs/default.yaml` and a note in MEMORY.md.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field


class TrajectoryStep(BaseModel):
    """One step in a pipeline run."""
    step_index: int
    stage: str                                 # "plan" | "route_pages" | "localize" | ...
    tier: str                                  # "cheap" | "mid" | "frontier"
    action: str                                # e.g. "llm_call" | "tool_call" | "deterministic"
    tool: str | None = None                    # for tool_call: the tool name
    args: dict[str, Any] = Field(default_factory=dict)
    obs_ref: str | None = None                 # content-addressed ref into cache
    obs_summary: str | None = None             # short human-readable summary
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    usd: float | None = None
    confidence: float | None = None


class RunTrace(BaseModel):
    example_id: str
    question: str
    plan: dict[str, Any] = Field(default_factory=dict)
    steps: list[TrajectoryStep] = Field(default_factory=list)
    final_answer: str | None = None
    final_citations: list[dict[str, Any]] = Field(default_factory=list)
    reward: dict[str, float] | None = None
    started_at: float = Field(default_factory=time.time)
    ended_at: float | None = None


class TrajectoryRecorder:
    """Collects steps during a workflow run. Intended to be created per-example."""

    def __init__(self, example_id: str, question: str) -> None:
        self._trace = RunTrace(example_id=example_id, question=question)

    def set_plan(self, plan: dict[str, Any]) -> None:
        self._trace.plan = plan

    def record(self, step: TrajectoryStep) -> None:
        self._trace.steps.append(step)

    def finalize(
        self,
        *,
        answer: str | None,
        citations: list[dict[str, Any]] | None = None,
        reward: dict[str, float] | None = None,
    ) -> RunTrace:
        self._trace.final_answer = answer
        self._trace.final_citations = citations or []
        self._trace.reward = reward
        self._trace.ended_at = time.time()
        return self._trace
