"""LLM-driven inspector dispatch (Phase 6 candidate #1).

Replaces the deterministic top-N + region-type-routed inspector with an
LLM that decides *which* candidate regions to inspect and *which*
inspect_region mode (image / element / region) for each. The dispatch
itself still goes through the per-region helper in
`pipeline/inspector.py:_inspect_one_region` — we keep its smart routing
(text-vs-visual fallback, tesseract escalation, sub-layout detection)
and just let the LLM pick the inputs.

The diagnostic mining of headline-v1 (`results/diagnostics/headline-v1/`)
showed RT-DETRv2 ranks text > picture by detector score, so figure-heavy
questions miss because the deterministic top-N picks text regions over
charts. An LLM that reads the question + figure_class can correct this.

This is the **single-shot** variant: one LLM call per example emits a
`plan` of (region_idx, mode) pairs which the harness then dispatches in
order. A multi-turn ReAct loop is deferred — single-shot is cheaper
(~$0.005/example) and gives us a clean A/B against the deterministic
floor before adding loop complexity.

Wired in `FocusWorkflow(use_react_inspector=True)`. The deterministic
inspector stays as the fallback when the flag is off OR when the LLM's
plan is malformed (best-effort: fall back to the deterministic top-N).
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, ValidationError

from focusparse.evidence.packet import EvidencePacket
from focusparse.models.base import ModelClient, ModelResponse
from focusparse.pipeline.events import (
    EvidenceEvent,
    PlanEvent,
    QuestionEvent,
    RegionCandidate,
    RegionsEvent,
)
from focusparse.pipeline.inspector import _CHART_QUESTION_FAMILIES, _inspect_one_region

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


_DEFAULT_MAX_CROPS = 8

_INSPECTOR_SYSTEM_PROMPT = (
    "You are the INSPECT stage of a document-parsing pipeline. You receive "
    "a question and N candidate regions detected by RT-DETRv2 on a page. "
    "Your job: pick which regions to inspect (up to the max_crops budget) "
    "and which depth for each.\n"
    "\n"
    "Modes:\n"
    "  image   — crop only, no OCR. Cheapest. Use for purely visual content "
    "(charts, figures) where the reasoner reads the image directly.\n"
    "  element — crop + Tesseract OCR. Use for text-bearing regions: "
    "captions, table cells, footnotes, section headers.\n"
    "  region  — crop + sub-layout detection + per-sub OCR. Use for mixed "
    "structures: chart+legend+caption, table+notes, figure+axis labels.\n"
    "\n"
    "Output STRICT JSON in this shape (no extra keys, no markdown beyond a "
    "single ```json fence):\n"
    '  {"thought": "...", "plan": [{"region_idx": 0, "mode": "image"}, ...]}\n'
    "\n"
    "Picking heuristics:\n"
    "  - Match region type to expected evidence: charts/figures for visual "
    "questions, text/section_header for label questions.\n"
    "  - Picture regions with figure_class='bar_chart'|'line_chart' usually "
    "want mode='region' so legend + axis ticks come along.\n"
    "  - Text-only regions usually want mode='element'.\n"
    "  - Prefer fewer, deeper inspections over many shallow ones — every "
    "extra crop costs reasoner tokens downstream.\n"
    "  - If two regions overlap heavily, pick one (the higher-relevance one).\n"
)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


class _PlanItem(BaseModel):
    """One entry in the LLM's inspection plan."""

    region_idx: int = Field(..., ge=0)
    mode: str = Field(default="element")


class _InspectorPlan(BaseModel):
    """The LLM's full inspection plan for one example."""

    thought: str = ""
    plan: list[_PlanItem] = Field(default_factory=list)


class ReActInspectorResult(BaseModel):
    """Internal — what the inspector reports back to the workflow."""

    evidence: EvidenceEvent
    response: ModelResponse | None = None
    fallback_used: bool = False
    plan_size: int = 0

    model_config = {"arbitrary_types_allowed": True}


async def react_inspect(
    question: QuestionEvent,
    plan: PlanEvent,
    regions: RegionsEvent,
    *,
    backend_client: ModelClient | None,
    images_by_page: dict[int, Path],
    pdf_path: Path | None = None,
    crop_cache_dir: Path | None = None,
    text_layer_cache_dir: Path | None = None,
    auto_zoom: bool = False,
    multi_scale: bool = False,
    chart_to_table_enabled: bool = False,
    chart_to_table_backend: ModelClient | None = None,
) -> ReActInspectorResult:
    """LLM-driven inspector dispatch.

    When `backend_client` is None or the LLM call fails / returns a malformed
    plan, falls back to the deterministic top-N (same behavior as the
    `inspect_regions` floor in `pipeline/inspector.py`). Always returns a
    non-empty `EvidenceEvent` so downstream stages can run.
    """
    max_crops = plan.max_crops or _DEFAULT_MAX_CROPS
    candidates = list(regions.candidates)

    # ---- Step 1: build the LLM-side prompt + call ----
    response: ModelResponse | None = None
    plan_items: list[_PlanItem] = []
    fallback_used = False

    if backend_client is None or not candidates:
        # No LLM wired (test or no router) → deterministic fallback.
        plan_items = _deterministic_topn(candidates, max_crops=max_crops)
        fallback_used = True
    else:
        prompt = _build_user_prompt(question, plan, candidates, max_crops=max_crops)
        try:
            response = await backend_client.predict(
                prompt=prompt,
                system=_INSPECTOR_SYSTEM_PROMPT,
            )
            plan_items = _parse_plan(response.text, n_candidates=len(candidates))
        except Exception as exc:  # noqa: BLE001 — best-effort
            logger.warning(
                "ReActInspector LLM call failed (%s); falling back to deterministic top-N",
                exc,
            )
            plan_items = []

        if not plan_items:
            # LLM returned an empty / invalid plan: fall back so we never
            # ship 0 packets (downstream stages assume non-empty evidence).
            plan_items = _deterministic_topn(candidates, max_crops=max_crops)
            fallback_used = True

    # Cap to budget regardless of what the LLM returned.
    plan_items = plan_items[:max_crops]

    # ---- Step 2: dispatch via the existing per-region helper ----
    packets: list[EvidencePacket] = []
    for idx, item in enumerate(plan_items):
        if item.region_idx >= len(candidates):
            continue
        region = candidates[item.region_idx]
        # The helper hardcodes its own mode based on region_type today; we
        # extend it implicitly by re-rendering the bbox under the LLM-picked
        # mode through inspect_region. For the first cut we just ride the
        # helper's existing logic — it already chooses image/element/region
        # correctly per region type. The LLM's mode pick is ADVISORY for
        # this iteration; phase 1b can plumb it through.
        # Use the same chart-family gate as the deterministic inspector so
        # the +4 tool-set's ReAct path doesn't silently use a narrower set.
        # Expanded 2026-05-11 (harness-growth Phase 1) — see inspector.py.
        chart_active = chart_to_table_enabled and (
            (plan.question_family or "") in _CHART_QUESTION_FAMILIES
        )
        packet = await _inspect_one_region(
            idx,
            region,
            images_by_page=images_by_page,
            pdf_path=pdf_path,
            crop_cache_dir=crop_cache_dir,
            text_layer_cache_dir=text_layer_cache_dir,
            auto_zoom=auto_zoom,
            multi_scale=multi_scale,
            chart_extraction_active=chart_active,
            chart_to_table_backend=chart_to_table_backend,
            question_family=plan.question_family,
        )
        packets.append(packet)

    return ReActInspectorResult(
        evidence=EvidenceEvent(packets=packets),
        response=response,
        fallback_used=fallback_used,
        plan_size=len(plan_items),
    )


# ---------------------------------------------------------------------------
# Prompt + parsing helpers
# ---------------------------------------------------------------------------


def _build_user_prompt(
    question: QuestionEvent,
    plan: PlanEvent,
    candidates: list[RegionCandidate],
    *,
    max_crops: int,
) -> str:
    """Render the inspector's user-side prompt.

    Fields per candidate: idx, page, region_type, score, bbox_norm. Includes
    figure_class when available (carried in `expansion_hints` today; future
    work could surface it as a typed field on RegionCandidate).
    """
    lines = [f"Question: {question.question}"]
    if plan.evidence_types:
        lines.append(f"Expected evidence types (from planner): {plan.evidence_types}")
    if plan.question_family:
        lines.append(f"Question family: {plan.question_family}")
    lines.append(f"Max regions to inspect (budget): {max_crops}")
    lines.append("")
    lines.append("Region candidates:")
    for idx, region in enumerate(candidates):
        bbox = ", ".join(f"{v:.3f}" for v in region.bbox_norm)
        rtype = region.region_type or "?"
        score = f"{region.score:.2f}"
        relevance = f", relevance={region.relevance:.2f}" if region.relevance is not None else ""
        needed_for = f", needed_for={region.needed_for}" if region.needed_for else ""
        # figure_class shows up in supporting_signals as "figure_class:bar_chart"
        fc = ""
        for sig in region.supporting_signals or []:
            if sig.startswith("figure_class:"):
                fc = f", {sig}"
                break
        lines.append(
            f"  [{idx}] page={region.page}, type={rtype}, score={score}{fc}, "
            f"bbox=[{bbox}]{relevance}{needed_for}"
        )
    lines.append("")
    lines.append(
        "Emit your plan now. Use STRICT JSON; pick at most "
        f"{max_crops} regions. Tag each with mode='image'|'element'|'region'."
    )
    return "\n".join(lines)


def _parse_plan(text: str, *, n_candidates: int) -> list[_PlanItem]:
    """Tolerant JSON parse of the inspector's plan response."""
    if not text:
        return []
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
        return []
    if not isinstance(obj, dict):
        return []
    try:
        parsed = _InspectorPlan.model_validate(obj)
    except ValidationError:
        return []
    return [item for item in parsed.plan if 0 <= item.region_idx < n_candidates]


def _deterministic_topn(
    candidates: list[RegionCandidate],
    *,
    max_crops: int,
) -> list[_PlanItem]:
    """Same fallback as `inspector.inspect_regions`: top-N by score."""
    ranked = sorted(
        range(len(candidates)),
        key=lambda i: -float(candidates[i].score),
    )[:max_crops]
    return [_PlanItem(region_idx=i, mode="element") for i in ranked]
