"""VERIFY stage — mid-tier support check + escalation policy.

Two code paths share one signature:
  * **Deterministic fallback** (no `backend_client`): accept everything,
    propagate the reasoner's confidence. Used by unit tests and offline runs.
  * **Mid-tier LLM** (with `backend_client`): calls the verifier tier for a
    strict-JSON support check, then maps its `next_action` into our enum.

Failure-mode taxonomy (plan §11) the verifier is allowed to emit:
  - `accept`              — evidence supports the answer
  - `retry_localization`  — right answer, wrong citation; re-crop
  - `expand_context`      — evidence incomplete; widen crops
  - `abstain`             — conflicting evidence, safer to say "unanswerable"
  - `escalate_reasoner`   — evidence is there, reasoner mis-read it

The LLM path is tolerant by design: any field the model fails to emit (or
emits outside the allowed set) falls back to the deterministic default. We
never let a malformed verifier response break downstream stages.

Note: 2d lands the LLM call and the emitted `next_action`; the actual retry
loop in `FocusWorkflow` (following the verdict's `next_action` back into
localize/expand) is a later sub-phase. For now the verdict is recorded on
the trajectory and the workflow still terminates after a single pass.
"""

from __future__ import annotations

import json
import re
from typing import Any

from focusparse.evidence.packet import EvidencePacket
from focusparse.models.base import ModelClient, ModelResponse
from focusparse.pipeline.events import (
    AnswerEvent,
    EvidenceEvent,
    QuestionEvent,
    VerdictEvent,
)

_VALID_NEXT_ACTIONS = frozenset(
    {
        "accept",
        "retry_localization",
        "expand_context",
        "abstain",
        "escalate_reasoner",
    }
)

_SYSTEM_PROMPT = (
    "You are a strict answer verifier for a document-QA pipeline. You are "
    "given a question, a list of evidence packets cited by the reasoner, and "
    "the reasoner's proposed answer. Decide whether the evidence supports "
    "the answer. Return STRICT JSON with keys `supported` (boolean), "
    "`reason` (short string, <= 240 chars), `next_action`, and `confidence` "
    "(float in [0, 1]). No prose outside the JSON.\n\n"
    "- `next_action` must be one of: accept | retry_localization | "
    "expand_context | abstain | escalate_reasoner.\n"
    "  * accept: evidence clearly supports the answer.\n"
    "  * retry_localization: answer is plausible but the cited region is "
    "wrong or too wide — re-crop around the right bbox.\n"
    "  * expand_context: the cited region is correct but missing a neighbor "
    "(caption, footnote, legend) needed to resolve the answer, or the cited "
    "visual crop/OCR is too small, blurry, garbled, or unreadable and needs a "
    "more readable crop of the same packet.\n"
    "  * abstain: evidence is contradictory or absent — safer to decline.\n"
    "  * escalate_reasoner: evidence is sufficient but the answer mis-read "
    "it — a stronger reasoner should retry.\n"
    "- Before accepting, check every explicit constraint in the question "
    "against the same cited row, entity, chart series, or page region: "
    "units, conditions, labels, qualifiers, domain tags (for example "
    "AEC-Q100), and superlatives such as lowest/highest/min/max. Reject "
    "answers that satisfy only a subset of the constraints or use a nearby "
    "but different row/entity.\n"
    "- When `next_action` is expand_context, include optional "
    "`diagnostics.missing_context` with any of: caption, legend, footnote, "
    "header, continuation, axis_label, row_header, column_header, unit, "
    "x_axis, y_axis.\n"
    "- If expand_context is for readability rather than missing context, keep "
    "`diagnostics.missing_context` empty and include "
    "`diagnostics.target_packet_ids` when you can name the affected packet.\n"
    "- Prefer `escalate_reasoner` over `expand_context` when the packet text "
    "already contains the needed labels, rows, numbers, units, or formula "
    "inputs, but the answer uses the wrong arithmetic or extracts the wrong "
    "value. Use `expand_context` only when you can name a missing neighboring "
    "caption, footnote, legend, header, or continuation that is not present in "
    "any packet summary.\n"
    "- `confidence` is your confidence in the verdict, not the answer."
)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_MAX_VERIFIER_PACKET_TEXT_CHARS = 500
_MAX_VERIFIER_CITED_PACKET_TEXT_CHARS = 900
_VERIFIER_FOCUS_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
        "what",
        "which",
    }
)


async def verify_answer(
    question: QuestionEvent,
    evidence: EvidenceEvent,
    answer: AnswerEvent,
    *,
    backend_client: ModelClient | None = None,
) -> tuple[VerdictEvent, ModelResponse | None]:
    """Verify that `evidence` supports `answer` for `question`.

    Args:
        question: the QuestionEvent (carries question text + domain).
        evidence: packets that were fed to the reasoner.
        answer: the reasoner's AnswerEvent (answer text + citations).
        backend_client: Optional mid-tier ModelClient. If None, the
            deterministic fallback is used and the response is `None`.

    Returns:
        `(VerdictEvent, ModelResponse | None)`. The raw response lets the
        workflow attribute tokens and cost to the verify step.
    """
    fallback = _deterministic_verdict(answer)

    if backend_client is None:
        return fallback, None

    prompt = _build_verifier_prompt(question, evidence, answer)
    response = await backend_client.predict(
        prompt=prompt,
        images=None,
        system=_SYSTEM_PROMPT,
    )

    parsed = _parse_verifier_response(response.text)
    supported = parsed.get("supported", fallback.supported)
    reason = parsed.get("reason") or fallback.reason
    next_action = parsed.get("next_action") or fallback.next_action
    confidence = parsed.get("confidence", fallback.confidence)
    diagnostics = parsed.get("diagnostics", fallback.diagnostics)
    next_action, diagnostics = _reconcile_supported_next_action(
        supported=supported,
        next_action=next_action,
        diagnostics=diagnostics,
    )
    verdict = VerdictEvent(
        supported=supported,
        reason=reason,
        next_action=next_action,
        confidence=confidence,
        diagnostics=diagnostics,
    )
    return verdict, response


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _deterministic_verdict(answer: AnswerEvent) -> VerdictEvent:
    return VerdictEvent(
        supported=True,
        reason="skeleton_always_accept",
        next_action="accept",
        confidence=answer.confidence,
    )


def _build_verifier_prompt(
    question: QuestionEvent,
    evidence: EvidenceEvent,
    answer: AnswerEvent,
) -> str:
    cited_packet_ids = set(answer.citations)
    focus_text = f"{question.question}\nProposed answer: {answer.answer}"
    packet_lines = [
        _summarize_packet(
            p,
            cited=p.packet_id in cited_packet_ids,
            question_text=focus_text,
            answer_text=answer.answer,
        )
        for p in evidence.packets
    ]
    if not packet_lines:
        packet_block = "(no evidence packets were cited)"
    else:
        packet_block = "\n".join(packet_lines)

    citations = ", ".join(answer.citations) if answer.citations else "(none)"
    domain_line = f"Document domain: {question.domain}\n" if question.domain else ""
    return (
        f"{domain_line}"
        f"Question: {question.question}\n\n"
        f"Evidence packets the reasoner had access to:\n{packet_block}\n\n"
        f"Reasoner's answer: {answer.answer}\n"
        f"Reasoner's cited packet_ids: {citations}\n"
        f"Reasoner's self-reported confidence: {answer.confidence:.2f}\n\n"
        "Return only the JSON object."
    )


def _summarize_packet(
    packet: EvidencePacket,
    *,
    cited: bool = False,
    question_text: str | None = None,
    answer_text: str | None = None,
) -> str:
    """One-line packet summary for the verifier prompt.

    Keep it compact — the verifier tier is cheap and long packets balloon the
    prompt cost without helping binary support decisions.
    """
    snippet = packet.text_layer_snippet or packet.ocr_snippet or ""
    snippet = _focused_packet_text(
        snippet,
        question_text=question_text,
        answer_text=answer_text if cited else None,
    )
    snippet = snippet.strip().replace("\n", " ")
    max_chars = _MAX_VERIFIER_CITED_PACKET_TEXT_CHARS if cited else _MAX_VERIFIER_PACKET_TEXT_CHARS
    if len(snippet) > max_chars:
        snippet = snippet[: max_chars - 3] + "..."
    region = packet.region_type or "region"
    scale_part = ""
    if packet.multi_scale_crops:
        scale_part = " scales=" + _fmt_scales(packet.multi_scale_crops)
    cited_part = " cited_by_answer=yes" if cited else " cited_by_answer=no"
    return (
        f"- [{packet.packet_id}] page={packet.page} type={region} "
        f"bbox={_fmt_bbox(packet.bbox_norm)}{scale_part}{cited_part} text={snippet!r}"
    )


def _focused_packet_text(
    text: str,
    *,
    question_text: str | None = None,
    answer_text: str | None = None,
) -> str:
    """Put exact answer rows before broader question-matching context."""
    answer_focused = _answer_focused_text(text, answer_text=answer_text)
    question_focused = _question_focused_text(text, question_text=question_text)
    if not answer_focused:
        return question_focused
    if not question_focused or question_focused == text or question_focused in answer_focused:
        return answer_focused
    return f"{answer_focused} / {question_focused}"


def _answer_focused_text(text: str, *, answer_text: str | None = None) -> str:
    """Surface rows that literally contain the proposed answer.

    Question overlap alone can prefer nearby distractor rows (for example a
    linked context-ID row) over the exact row cited by the answer. The verifier
    needs the answer-bearing row first so support checks are about the proposed
    answer, not just the most lexical-overlap-heavy row.
    """
    if not text or not answer_text:
        return ""
    answer = answer_text.strip()
    if not answer or answer.lower() == "unanswerable":
        return ""
    answer_tokens = _focus_tokens(answer)
    if not answer_tokens:
        return ""

    normalized_answer = _normalize_match_text(answer)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    selected_indexes: set[int] = set()
    for idx, line in enumerate(lines):
        line_tokens = _focus_tokens(line)
        if normalized_answer in _normalize_match_text(line) or answer_tokens <= line_tokens:
            selected_indexes.update({idx - 1, idx, idx + 1, idx + 2})
        if len(selected_indexes) >= 12:
            break
    if not selected_indexes:
        return ""
    return " / ".join(lines[idx] for idx in sorted(selected_indexes) if 0 <= idx < len(lines))


def _question_focused_text(text: str, *, question_text: str | None = None) -> str:
    """Surface question-matching rows in long packet summaries for verification."""
    if not text or not question_text or len(text) <= _MAX_VERIFIER_PACKET_TEXT_CHARS:
        return text
    q_tokens = _focus_tokens(question_text)
    if not q_tokens:
        return text

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    scored: list[tuple[int, int]] = []
    for idx, line in enumerate(lines):
        overlap = len(q_tokens & _focus_tokens(line))
        if overlap:
            scored.append((overlap, idx))
    if not scored:
        return text

    max_score = max(score for score, _idx in scored)
    score_floor = max(1, max_score - 1)
    selected_indexes: set[int] = set()
    for _score, idx in [
        item
        for item in sorted(scored, key=lambda item: (-item[0], item[1]))
        if item[0] >= score_floor
    ][:4]:
        selected_indexes.update({idx - 1, idx, idx + 1})
    selected = [lines[idx] for idx in sorted(selected_indexes) if 0 <= idx < len(lines)]
    return " / ".join(selected)


def _focus_tokens(text: str) -> set[str]:
    tokens = set(re.findall(r"[a-z0-9]+", text.lower()))
    return {tok for tok in tokens if len(tok) > 1 and tok not in _VERIFIER_FOCUS_STOPWORDS}


def _normalize_match_text(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def _fmt_scales(crops: list) -> str:
    return "[" + ", ".join(f"{c.scale}:{_fmt_bbox(c.bbox_norm)}" for c in crops) + "]"


def _fmt_bbox(bbox: tuple[float, float, float, float]) -> str:
    return "[" + ", ".join(f"{v:.3f}" for v in bbox) + "]"


def _parse_verifier_response(text: str | None) -> dict[str, Any]:
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

    supported = obj.get("supported")
    if isinstance(supported, bool):
        out["supported"] = supported

    reason = obj.get("reason")
    if isinstance(reason, str) and reason.strip():
        out["reason"] = reason.strip()[:240]

    next_action = obj.get("next_action")
    if isinstance(next_action, str):
        normalized_action = _normalize_next_action(next_action)
        if normalized_action is not None:
            out["next_action"] = normalized_action

    confidence = obj.get("confidence")
    if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
        c = float(confidence)
        if 0.0 <= c <= 1.0:
            out["confidence"] = c

    diagnostics = _parse_diagnostics(
        obj.get("diagnostics"),
        reason=out.get("reason"),
    )
    if diagnostics:
        out["diagnostics"] = diagnostics

    return out


def _normalize_next_action(value: str) -> str | None:
    """Accept common enum spelling variants while rejecting unknown actions."""
    normalized = value.strip().lower()
    normalized = normalized.strip("`'\".,;:()[]{}")
    normalized = re.sub(r"[\s\-]+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized)
    if normalized in _VALID_NEXT_ACTIONS:
        return normalized
    return None


def _reconcile_supported_next_action(
    *,
    supported: bool,
    next_action: str,
    diagnostics: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Make verifier control-flow fields internally consistent."""
    if supported:
        if next_action != "accept":
            diagnostics = dict(diagnostics)
            diagnostics["normalized_next_action"] = next_action
        return "accept", diagnostics
    if next_action == "accept":
        diagnostics = dict(diagnostics)
        diagnostics["normalized_next_action"] = "accept"
        if diagnostics.get("missing_context"):
            return "expand_context", diagnostics
        return "escalate_reasoner", diagnostics
    return next_action, diagnostics


def _parse_diagnostics(raw: Any, *, reason: str | None = None) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {}
    missing_context: list[str] = []
    target_packet_ids: list[str] = []

    if isinstance(raw, dict):
        missing_context.extend(_normalize_missing_context_values(raw.get("missing_context")))
        packet_ids = raw.get("target_packet_ids")
        if isinstance(packet_ids, str):
            packet_ids = [packet_ids]
        if isinstance(packet_ids, list):
            for packet_id in packet_ids:
                if isinstance(packet_id, str) and packet_id.strip():
                    target_packet_ids.append(packet_id.strip()[:80])

    missing_context.extend(_missing_context_from_text(reason))
    missing_context = _dedupe_preserve_order(missing_context)
    target_packet_ids = _dedupe_preserve_order(target_packet_ids)

    if missing_context:
        diagnostics["missing_context"] = missing_context
    if target_packet_ids:
        diagnostics["target_packet_ids"] = target_packet_ids
    return diagnostics


def _normalize_missing_context_values(raw: Any) -> list[str]:
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    normalized: list[str] = []
    for value in raw:
        if not isinstance(value, str):
            continue
        context = _normalize_missing_context_value(value)
        if context is not None:
            normalized.append(context)
    return normalized


def _normalize_missing_context_value(value: str) -> str | None:
    key = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    aliases = {
        "axis": "axis_label",
        "axis_label": "axis_label",
        "axis_labels": "axis_label",
        "tick_label": "axis_label",
        "tick_labels": "axis_label",
        "caption": "caption",
        "captions": "caption",
        "column_header": "column_header",
        "column_headers": "column_header",
        "column_label": "column_header",
        "column_labels": "column_header",
        "continued": "continuation",
        "continued_table": "continuation",
        "continuation": "continuation",
        "footer": "header",
        "footnote": "footnote",
        "footnotes": "footnote",
        "header": "header",
        "headers": "header",
        "legend": "legend",
        "legends": "legend",
        "next_page": "continuation",
        "note": "footnote",
        "notes": "footnote",
        "page_footer": "header",
        "page_header": "header",
        "previous_page": "continuation",
        "row_header": "row_header",
        "row_headers": "row_header",
        "row_label": "row_header",
        "row_labels": "row_header",
        "section_header": "header",
        "title": "header",
        "unit": "unit",
        "units": "unit",
        "x_axis": "x_axis",
        "x_axis_label": "x_axis",
        "y_axis": "y_axis",
        "y_axis_label": "y_axis",
    }
    return aliases.get(key)


def _missing_context_from_text(reason: str | None) -> list[str]:
    if not reason:
        return []
    normalized = reason.lower()
    phrase_checks: tuple[tuple[tuple[str, ...], str], ...] = (
        (("x axis", "x-axis"), "x_axis"),
        (("y axis", "y-axis"), "y_axis"),
        (("axis label", "axis labels", "tick label", "tick labels"), "axis_label"),
        (("caption", "captions"), "caption"),
        (("column header", "column label"), "column_header"),
        (("row header", "row label"), "row_header"),
        (("footnote", "footnotes", "note", "notes"), "footnote"),
        (("legend", "legends"), "legend"),
        (
            ("continued table", "continuation", "continued on", "next page", "previous page"),
            "continuation",
        ),
        (("section header", "header", "headers", "title"), "header"),
        (("unit", "units"), "unit"),
    )
    found: list[str] = []
    for needles, context in phrase_checks:
        if any(needle in normalized for needle in needles):
            found.append(context)
    return found


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
