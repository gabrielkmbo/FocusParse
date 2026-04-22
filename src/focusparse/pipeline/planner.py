"""PLAN stage — classify question family, set budget, choose routing policy.

Two code paths share one signature:
  * **Deterministic fallback** (no `backend_client`): emits a neutral plan.
    Used by unit tests and by workflows running offline.
  * **Cheap-tier LLM** (with `backend_client`): calls the cheap tier for a
    strict-JSON classification of question_family, evidence_types,
    routing_policy, budget_class, then fills budget fields from config.

The LLM path is tolerant by design — any field the model fails to emit (or
emits outside the allowed set) falls back to the deterministic default. We
never let a malformed planner response break downstream stages.
"""

from __future__ import annotations

import json
import re
from typing import Any

from focusparse.models.base import ModelClient, ModelResponse
from focusparse.pipeline.events import PlanEvent, QuestionEvent
from focusparse.utils.config import BudgetSpec

# Domain-specific question families (parser-bench schema). The union is all we
# ever accept as valid `question_family` output from the LLM.
_DATASHEET_FAMILIES = frozenset(
    {
        "spec_table_cell_retrieval",
        "min_typ_max_disambiguation",
        "condition_footnote_fusion",
        "curve_axis_reading",
        "figure_caption_cross_ref",
        "table_note_fusion",
        "pin_diagram_label",
        "package_mechanical_reading",
        "cross_page_continuation",
        "distant_evidence_fusion",
        "near_miss_distractor",
        "footnote_critical",
        "confusable_label",
        "schematic_value_lookup",
        "timing_diagram_reading",
        "unanswerable",
    }
)
_FINANCE_FAMILIES = frozenset(
    {
        "direct_label_reading",
        "axis_value_interpolation",
        "legend_series_binding",
        "dual_axis_disambiguation",
        "chart_footnote_fusion",
        "chart_caption_fusion",
        "chart_table_cross_ref",
        "multi_chart_comparison",
        "candlestick_ohlc_extraction",
        "distant_evidence_fusion",
        "near_miss_distractor",
        "footnote_critical",
        "confusable_label",
        "unanswerable",
    }
)
_ALL_FAMILIES = _DATASHEET_FAMILIES | _FINANCE_FAMILIES

_VALID_BUDGET_CLASSES = frozenset({"easy_local", "multi_region", "cross_page", "highres_tiny"})
_VALID_ROUTING_POLICIES = frozenset({"text_first", "layout_first", "image_first", "hybrid"})
_VALID_EVIDENCE_TYPES = frozenset(
    {
        "text",
        "image",
        "table",
        "chart",
        "figure",
        "caption",
        "footnote",
        "legend",
        "axis_label",
        "pin_diagram",
        "schematic",
        "timing_diagram",
    }
)

_SYSTEM_PROMPT = (
    "You classify document questions so a downstream agentic pipeline can "
    "budget tool calls and pick a routing policy. Return STRICT JSON with "
    "keys `question_family`, `evidence_types`, `budget_class`, "
    "`routing_policy`. Do not add extra keys. No prose.\n\n"
    "- `question_family`: one of the domain-specific family strings listed in "
    "the user prompt.\n"
    "- `evidence_types`: list of region types that likely support the answer "
    "(e.g. ['chart', 'legend'] or ['table']).\n"
    "- `budget_class`: one of easy_local | multi_region | cross_page | "
    "highres_tiny.\n"
    "- `routing_policy`: one of text_first | layout_first | image_first | "
    "hybrid."
)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


async def plan_question(
    event: QuestionEvent,
    *,
    budget: BudgetSpec | None = None,
    backend_client: ModelClient | None = None,
    domain: str | None = None,
) -> tuple[PlanEvent, ModelResponse | None]:
    """Plan the run.

    Args:
        event: QuestionEvent carrying the question text.
        budget: BudgetSpec from config. Sets `max_tool_calls`, `max_crops`,
            `max_vlm_calls`. Default = `BudgetSpec()` (stock defaults).
        backend_client: Optional cheap-tier ModelClient. If None, the
            deterministic fallback is used and the response is `None`.
        domain: "datasheet" | "finance" | None. Narrows the allowed
            `question_family` set if known; falls back to the union otherwise.

    Returns:
        `(PlanEvent, ModelResponse | None)`. The raw response lets the
        workflow attribute tokens and cost to the plan step.
    """
    budget = budget or BudgetSpec()
    domain = domain or event.domain
    fallback = _deterministic_plan(budget)

    if backend_client is None:
        return fallback, None

    families = _families_for_domain(domain)
    prompt = _build_planner_prompt(event.question, domain, families)
    response = await backend_client.predict(
        prompt=prompt,
        images=None,
        system=_SYSTEM_PROMPT,
    )

    parsed = _parse_planner_response(response.text, allowed_families=families)
    plan = PlanEvent(
        question_family=parsed.get("question_family") or fallback.question_family,
        evidence_types=parsed.get("evidence_types") or fallback.evidence_types,
        budget_class=parsed.get("budget_class") or fallback.budget_class,
        routing_policy=parsed.get("routing_policy") or fallback.routing_policy,
        max_tool_calls=budget.tool_calls,
        max_crops=budget.crops,
        max_vlm_calls=budget.max_vlm_calls,
    )
    return plan, response


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _deterministic_plan(budget: BudgetSpec) -> PlanEvent:
    return PlanEvent(
        question_family="unknown",
        evidence_types=["text", "image"],
        budget_class="easy_local",
        routing_policy="hybrid",
        max_tool_calls=budget.tool_calls,
        max_crops=budget.crops,
        max_vlm_calls=budget.max_vlm_calls,
    )


def _families_for_domain(domain: str | None) -> frozenset[str]:
    if domain == "datasheet":
        return _DATASHEET_FAMILIES
    if domain == "finance":
        return _FINANCE_FAMILIES
    return _ALL_FAMILIES


def _build_planner_prompt(
    question: str,
    domain: str | None,
    families: frozenset[str],
) -> str:
    family_list = ", ".join(sorted(families))
    domain_line = f"Document domain: {domain}\n" if domain else ""
    return (
        f"{domain_line}"
        f"Allowed question_family values: {family_list}\n\n"
        f"Question: {question}\n\n"
        "Return only the JSON object."
    )


def _parse_planner_response(
    text: str | None,
    *,
    allowed_families: frozenset[str],
) -> dict[str, Any]:
    """Extract whatever valid fields we can from the LLM reply.

    Unknown keys and malformed values are silently dropped; the caller fills
    gaps from the deterministic fallback.
    """
    if not text:
        return {}

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
        return {}
    if not isinstance(obj, dict):
        return {}

    out: dict[str, Any] = {}

    fam = obj.get("question_family")
    if isinstance(fam, str) and fam in allowed_families:
        out["question_family"] = fam

    ev_types = obj.get("evidence_types")
    if isinstance(ev_types, list):
        clean = [t for t in ev_types if isinstance(t, str) and t in _VALID_EVIDENCE_TYPES]
        if clean:
            out["evidence_types"] = clean

    bc = obj.get("budget_class")
    if isinstance(bc, str) and bc in _VALID_BUDGET_CLASSES:
        out["budget_class"] = bc

    rp = obj.get("routing_policy")
    if isinstance(rp, str) and rp in _VALID_ROUTING_POLICIES:
        out["routing_policy"] = rp

    return out
