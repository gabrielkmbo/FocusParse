"""Typed events that flow between @step modules.

Convention: every event is a pydantic BaseModel, with no dict-shaped payloads.
The reasoner receives `EvidenceEvent(packets=...)` — never raw pages.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from focusparse.evidence.packet import EvidencePacket


class QuestionEvent(BaseModel):
    example_id: str
    question: str
    doc_id: str
    pages_available: int
    domain: str | None = None  # "finance" | "datasheet" | None
    # Answer-type stem ("numeric"/"exact_match"/"boolean"/"multiple_choice"/
    # "unanswerable"). Optional so legacy callers (older tests) don't break;
    # when present, the reasoner appends a type-aware format hint that
    # mirrors `SimpleBaselineAgent._format_hint`.
    answer_type: str | None = None


class PlanEvent(BaseModel):
    question_family: str
    evidence_types: list[str]  # e.g. ["chart", "legend", "footnote"]
    budget_class: Literal["easy_local", "multi_region", "cross_page", "highres_tiny"]
    routing_policy: Literal["text_first", "layout_first", "image_first", "hybrid"]
    max_tool_calls: int
    max_crops: int
    max_vlm_calls: int


class PageCandidate(BaseModel):
    page: int  # 1-indexed
    score: float
    reason_code: str  # e.g. "ocr_keyword_match", "layout_chart_prior"


class PagesEvent(BaseModel):
    candidates: list[PageCandidate]


class RegionCandidate(BaseModel):
    region_id: str
    page: int
    bbox_norm: tuple[float, float, float, float]
    region_type: str | None = None
    score: float
    supporting_signals: list[str] = Field(default_factory=list)
    expansion_hints: list[str] = Field(default_factory=list)
    # Item 4 (region reranker): query-conditioned relevance ∈ [0, 1] from
    # the mid-tier rerank stage, and a coarse role telling the inspector +
    # expander what this region is for (legend_binding, axis_reading,
    # caption_context, footnote_adjustment, table_cell_lookup,
    # header_disambiguation, primary). None when the rerank stage
    # didn't run (no tier_router wired) or the rerank failed.
    relevance: float | None = None
    needed_for: str | None = None


class RegionsEvent(BaseModel):
    candidates: list[RegionCandidate]


class EvidenceEvent(BaseModel):
    packets: list[EvidencePacket]


class AnswerEvent(BaseModel):
    answer: str
    citations: list[str]  # EvidencePacket.packet_id refs
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning_summary: str | None = None


class VerdictEvent(BaseModel):
    supported: bool
    reason: str
    next_action: Literal[
        "accept",
        "retry_localization",
        "expand_context",
        "abstain",
        "escalate_reasoner",
    ]
    confidence: float = Field(ge=0.0, le=1.0)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
