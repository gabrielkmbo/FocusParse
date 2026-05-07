"""REGION_RERANK stage — query-conditioned relevance scoring (Phase 2 item 4).

The localizer (RT-DETRv2) returns layout boxes — "what's on this page?" — but
not "which boxes answer THIS question?" Top-N by detector score biases toward
text regions because RT-DETRv2 calibrates higher confidence on text. The
n=30 baseline (2026-04-27) showed strong localization (region_recall=0.689,
bbox_iou_mean=0.716) but the cited regions are often near-but-not-the-answer.

This stage adds a mid-tier LLM call between `propose_regions` and
`inspect_regions` that:

  1. Reads the question + plan + the localizer's regions (with type,
     bbox, detector score).
  2. Returns per-region relevance ∈ [0, 1] + a coarse `needed_for` role
     + `missing_context` hints for the expander.
  3. The workflow re-orders regions by `relevance * det_score` so the
     inspector's top-N picks question-relevant boxes, not just confident
     boxes. `expansion_hints` from `missing_context` flow into the
     expander so it knows which neighbor types to prefer.

Two code paths share one signature:

  * **Skip path** (no `backend_client`): return regions unchanged. Used
    by tests that don't wire a tier_router and by runs where the rerank
    tier isn't configured. The downstream stages still see a valid
    `RegionsEvent`.
  * **Mid-tier LLM** (with `backend_client`): JSON-shaped response;
    malformed entries are silently skipped. Regions that the LLM didn't
    score keep their original ranking — same fallback contract as the
    verifier.

The `needed_for` taxonomy is intentionally coarse: 7 roles. Anything
finer (e.g. specific axis tick) is the inspector's job, not the
ranker's. Roles map to inspector hints (which `inspect_region` mode
to use) and expander hints (which neighbor types to attach):

  * `primary`              — the region itself contains the answer
  * `legend_binding`       — chart legend; pair with the plot
  * `axis_reading`         — axis label / tick; pair with the plot
  * `caption_context`      — caption below a figure
  * `footnote_adjustment`  — adjusts numbers (margin / footnote)
  * `table_cell_lookup`    — specific cell; pair with header + condition
  * `header_disambiguation`— column / section header that resolves ambiguity
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from focusparse.models.base import ModelClient, ModelResponse
from focusparse.pipeline.events import (
    PlanEvent,
    QuestionEvent,
    RegionCandidate,
    RegionsEvent,
)

logger = logging.getLogger(__name__)

_VALID_NEEDED_FOR = frozenset(
    {
        "primary",
        "legend_binding",
        "axis_reading",
        "caption_context",
        "footnote_adjustment",
        "table_cell_lookup",
        "header_disambiguation",
    }
)

# `missing_context` entries that the expander knows how to attach as
# linked neighbors. Anything outside this set still propagates through
# but downstream consumers ignore unknown hints.
_VALID_MISSING_CONTEXT = frozenset(
    {
        "legend",
        "x_axis",
        "y_axis",
        "axis_label",
        "caption",
        "footnote",
        "header",
        "column_header",
        "row_header",
        "unit",
        "title",
        "section_header",
    }
)

_SYSTEM_PROMPT = (
    "You are a region reranker for a document-QA pipeline. You are given "
    "a question, a question family, and a list of layout regions detected "
    "on the page. For each region, return its relevance to the question "
    "and what it's for.\n\n"
    'Return STRICT JSON: `{"regions": [{...}, ...]}` with one object per '
    "input region. Each object must have:\n"
    "  - `region_id` (string, exact match to the input)\n"
    "  - `relevance` (float in [0, 1] — 1.0 = directly answers the "
    "question; 0.0 = irrelevant)\n"
    "  - `needed_for` (one of: primary | legend_binding | axis_reading "
    "| caption_context | footnote_adjustment | table_cell_lookup | "
    "header_disambiguation)\n"
    "  - `missing_context` (list of strings naming neighbor types the "
    "inspector should attach, e.g. legend, x_axis, footnote, caption, "
    "column_header, unit; empty list when the region is self-contained)\n\n"
    "No prose outside the JSON. Skip regions you can't classify — the "
    "fallback keeps original ranking. The reranker can only see region "
    "metadata (label, bbox, detector confidence, figure_class when the "
    "layout endpoint provided one), not the page image, so lean on "
    "`region_type`, `figure_class`, the question family, and bbox position."
)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


async def rerank_regions(
    question: QuestionEvent,
    plan: PlanEvent,
    regions: RegionsEvent,
    *,
    backend_client: ModelClient | None = None,
) -> tuple[RegionsEvent, ModelResponse | None]:
    """Re-rank regions by question-conditioned relevance.

    Returns a `(RegionsEvent, ModelResponse | None)` tuple. The raw
    response lets the workflow attribute tokens + cost to the rerank
    step. The response is None on the skip path.

    Mutations on the returned regions:
      * `relevance` ∈ [0, 1] when the LLM scored the region
      * `needed_for` ∈ `_VALID_NEEDED_FOR` when the LLM classified it
      * `expansion_hints` extended with the LLM's `missing_context` entries
        that pass `_VALID_MISSING_CONTEXT` (extends, doesn't replace)
      * `score` left unchanged — `relevance` is a separate signal
      * Sort order: descending by `relevance * score` when relevance is
        present, else falling back to `score` for un-scored regions

    The skip path returns the input regions unchanged so existing tests +
    callers without a tier_router keep working.
    """
    if backend_client is None or not regions.candidates:
        return regions, None

    prompt = _build_rerank_prompt(question, plan, regions)
    response = await backend_client.predict(
        prompt=prompt,
        images=None,
        system=_SYSTEM_PROMPT,
    )

    parsed = _parse_rerank_response(response.text)
    if not parsed:
        # LLM emitted nothing usable — return regions unchanged but
        # surface the response for trace cost attribution.
        return regions, response

    by_id = {r.region_id: r for r in regions.candidates}
    seen_ids: set[str] = set()
    updated: list[RegionCandidate] = []
    for entry in parsed:
        rid = entry["region_id"]
        original = by_id.get(rid)
        if original is None:
            continue  # LLM hallucinated a region id; ignore
        seen_ids.add(rid)
        updated.append(_apply_rerank_entry(original, entry))

    # Anything the LLM didn't score keeps its original record.
    for r in regions.candidates:
        if r.region_id not in seen_ids:
            updated.append(r)

    updated.sort(key=lambda r: -_combined_score(r))
    return RegionsEvent(candidates=updated), response


# ---------------------------------------------------------------------------
# Prompt + response handling
# ---------------------------------------------------------------------------


def _build_rerank_prompt(
    question: QuestionEvent,
    plan: PlanEvent,
    regions: RegionsEvent,
) -> str:
    region_lines = [
        f"- region_id={r.region_id} type={r.region_type or 'unknown'} "
        f"figure_class={_figure_class(r) or 'unknown'} "
        f"score={r.score:.3f} bbox={_fmt_bbox(r.bbox_norm)}"
        for r in regions.candidates
    ]
    domain_line = f"Document domain: {question.domain}\n" if question.domain else ""
    evidence_types_line = (
        f"Plan evidence_types: {plan.evidence_types}\n" if plan.evidence_types else ""
    )
    return (
        f"{domain_line}"
        f"Question: {question.question}\n"
        f"Question family: {plan.question_family}\n"
        f"{evidence_types_line}"
        f"\nRegions on the page:\n" + "\n".join(region_lines) + "\n\n"
        "Return only the JSON object."
    )


def _fmt_bbox(bbox: tuple[float, float, float, float]) -> str:
    return "[" + ", ".join(f"{v:.3f}" for v in bbox) + "]"


def _figure_class(region: RegionCandidate) -> str | None:
    """Return the localizer's figure subclass when present.

    Live localizer output uses `figure_class=<name>`; older tests/traces used
    `figure_class:<name>`. Preserve both because this prompt is a research
    diagnostic surface as much as a model input.
    """
    for sig in region.supporting_signals or []:
        if sig.startswith("figure_class=") or sig.startswith("figure_class:"):
            sep = "=" if "=" in sig else ":"
            value = sig.split(sep, 1)[1].strip().lower()
            return value or None
    return None


def _parse_rerank_response(text: str | None) -> list[dict[str, Any]]:
    """Extract a list of `{region_id, relevance, needed_for, missing_context}`
    dicts from the LLM reply. Malformed entries are silently dropped.
    """
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
        logger.debug("region_reranker: JSON parse failed on %r", text[:120])
        return []
    if not isinstance(obj, dict):
        return []

    raw_regions = obj.get("regions")
    if not isinstance(raw_regions, list):
        return []

    out: list[dict[str, Any]] = []
    for raw in raw_regions:
        if not isinstance(raw, dict):
            continue
        rid = raw.get("region_id")
        if not isinstance(rid, str) or not rid.strip():
            continue
        entry: dict[str, Any] = {"region_id": rid}

        rel = raw.get("relevance")
        if isinstance(rel, (int, float)) and not isinstance(rel, bool):
            r = float(rel)
            if 0.0 <= r <= 1.0:
                entry["relevance"] = r

        needed = raw.get("needed_for")
        if isinstance(needed, str) and needed in _VALID_NEEDED_FOR:
            entry["needed_for"] = needed

        hints = raw.get("missing_context")
        if isinstance(hints, list):
            kept = [h for h in hints if isinstance(h, str) and h in _VALID_MISSING_CONTEXT]
            if kept:
                entry["missing_context"] = kept

        if "relevance" in entry or "needed_for" in entry or "missing_context" in entry:
            out.append(entry)

    return out


def _apply_rerank_entry(region: RegionCandidate, entry: dict[str, Any]) -> RegionCandidate:
    """Merge an LLM rerank entry into a RegionCandidate, preserving fields
    the LLM didn't touch."""
    updates: dict[str, Any] = {}
    if "relevance" in entry:
        updates["relevance"] = entry["relevance"]
    if "needed_for" in entry:
        updates["needed_for"] = entry["needed_for"]
    if "missing_context" in entry:
        existing = list(region.expansion_hints)
        for hint in entry["missing_context"]:
            if hint not in existing:
                existing.append(hint)
        updates["expansion_hints"] = existing
    return region.model_copy(update=updates)


def _combined_score(region: RegionCandidate) -> float:
    """Sort key: relevance × det.score when relevance is set, else score.

    Multiplication keeps already-confident-and-relevant regions at the
    top, while a high-relevance / low-detector region (e.g. a small
    legend with low det confidence) can still beat a high-confidence
    irrelevant region.
    """
    if region.relevance is None:
        return float(region.score)
    return float(region.relevance) * float(region.score)
