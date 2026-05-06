"""In-workflow trajectory capture.

Every pipeline @step records a `TrajectoryStep`. At run end, `RunTrace` is
serialized to JSONL for later SFT (AgenticOCR recipe) or GRPO.

Schema contract: changes to TrajectoryStep / RunTrace fields require bumping
`SCHEMA_VERSION` in `traces/export.py` and a note in MEMORY.md.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field


class TrajectoryStep(BaseModel):
    """One step in a pipeline run."""

    step_index: int
    stage: str  # "plan" | "route_pages" | "localize" | ...
    tier: str  # "cheap" | "mid" | "frontier"
    action: str  # e.g. "llm_call" | "tool_call" | "deterministic"
    tool: str | None = None  # for tool_call: the tool name
    args: dict[str, Any] = Field(default_factory=dict)
    obs_ref: str | None = None  # content-addressed ref into cache
    obs_summary: str | None = None  # short human-readable summary
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    usd: float | None = None
    confidence: float | None = None


class EvidencePacketSummary(BaseModel):
    """JSON-safe subset of `evidence.packet.EvidencePacket` for snapshotting.

    Captured at workflow finalize time so the per-trace viewer (Phase 6
    sub-plan, 2026-05-04) can render what the reasoner saw without
    re-running the pipeline. Optional fields default to None so a
    comparator agent (ReAct, AgentBaseline) that doesn't construct
    `EvidencePacket`s can still snapshot whatever final tool outputs it
    has — pass a list of summaries with `local_crop_ref` set when a tool
    produced a crop, and the rest defaulted.
    """

    packet_id: str
    page: int
    bbox_norm: tuple[float, float, float, float]
    region_type: str | None = None
    local_crop_ref: str | None = None
    linked_crop_refs: list[str] = Field(default_factory=list)
    # Sprint Phase 2 (2026-05-04, Phase 6 #6): tight + context crops at
    # multiple scales. Each entry is {ref, bbox_norm, scale}; serialized
    # as raw dicts so the trace JSONL stays loose-typed for downstream
    # tooling (the viewer reads either local_crop_ref OR multi_scale_crops).
    multi_scale_crops: list[dict] = Field(default_factory=list)
    text_layer_snippet: str | None = None
    ocr_snippet: str | None = None
    # Sprint Phase 3 (2026-05-04, Phase 6 #7): chart_to_table extraction.
    # Populated only on chart regions for chart-reading questions.
    chart_csv: str | None = None
    chart_extraction_confidence: float | None = None
    confidence: float = 1.0
    provenance_tool: str | None = None


class TraceArtifact(BaseModel):
    """Reference to a trace-adjacent artifact without embedding bytes.

    Schema v3 keeps image/crop/chart/text payloads out of the JSON trace.
    Viewers resolve `path` or `ref` at render time and inline bytes only in
    the generated HTML artifact.
    """

    artifact_id: str
    kind: str  # "page_image" | "crop" | "thumbnail" | "chart_csv" | "text" | ...
    path: str | None = None
    ref: str | None = None
    page: int | None = None
    bbox_norm: tuple[float, float, float, float] | None = None
    packet_id: str | None = None
    stage: str | None = None
    step_index: int | None = None
    label: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class TraceDebugEvent(BaseModel):
    """Structured event for a human trace viewer.

    These events are intentionally loose-typed: each pipeline stage can emit
    concise, JSON-safe payloads without turning the SFT schema into a mirror
    of every internal event model.
    """

    event_id: str
    stage: str
    event_type: str
    step_index: int | None = None
    retry_attempt: int = 0
    payload: dict[str, Any] = Field(default_factory=dict)


class RunTrace(BaseModel):
    example_id: str
    question: str
    plan: dict[str, Any] = Field(default_factory=dict)
    steps: list[TrajectoryStep] = Field(default_factory=list)
    final_answer: str | None = None
    final_citations: list[dict[str, Any]] = Field(default_factory=list)
    reward: dict[str, float] | None = None
    # Schema v2 (2026-05-04): the final evidence the reasoner saw, snapshotted
    # at finalize time. Optional; legacy v1 traces serialize as None.
    evidence_snapshot: list[EvidencePacketSummary] | None = None
    # Schema v3 (2026-05-06): lightweight debug trail for one-example HTML
    # dashboards. Defaults preserve v1/v2 trace readability.
    artifacts: list[TraceArtifact] = Field(default_factory=list)
    debug_events: list[TraceDebugEvent] = Field(default_factory=list)
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

    def add_artifact(self, artifact: TraceArtifact | None = None, **kwargs: Any) -> TraceArtifact:
        """Attach an artifact reference and return the normalized model."""
        item = artifact if artifact is not None else TraceArtifact(**kwargs)
        self._trace.artifacts.append(item)
        return item

    def add_debug_event(
        self,
        event: TraceDebugEvent | None = None,
        **kwargs: Any,
    ) -> TraceDebugEvent:
        """Attach a structured debug event and return the normalized model."""
        item = event if event is not None else TraceDebugEvent(**kwargs)
        self._trace.debug_events.append(item)
        return item

    def next_debug_event_id(self, stage: str, event_type: str) -> str:
        """Stable per-trace id for the next debug event."""
        return f"{stage}:{event_type}:{len(self._trace.debug_events):03d}"

    def set_evidence_snapshot(self, packets: list[EvidencePacketSummary]) -> None:
        """Attach the final evidence packets the reasoner saw to the trace.

        Callers convert their workflow's `EvidencePacket` (or comparator
        tool outputs) to `EvidencePacketSummary` first; this keeps the
        trace schema decoupled from the in-memory packet shape.
        """
        self._trace.evidence_snapshot = list(packets)

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
