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
    "(caption, footnote, legend) needed to resolve the answer.\n"
    "  * abstain: evidence is contradictory or absent — safer to decline.\n"
    "  * escalate_reasoner: evidence is sufficient but the answer mis-read "
    "it — a stronger reasoner should retry.\n"
    "- `confidence` is your confidence in the verdict, not the answer."
)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


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
    verdict = VerdictEvent(
        supported=parsed.get("supported", fallback.supported),
        reason=parsed.get("reason") or fallback.reason,
        next_action=parsed.get("next_action") or fallback.next_action,
        confidence=parsed.get("confidence", fallback.confidence),
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
    packet_lines = [_summarize_packet(p) for p in evidence.packets]
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


def _summarize_packet(packet: EvidencePacket) -> str:
    """One-line packet summary for the verifier prompt.

    Keep it compact — the verifier tier is cheap and long packets balloon the
    prompt cost without helping binary support decisions.
    """
    snippet = packet.text_layer_snippet or packet.ocr_snippet or ""
    snippet = snippet.strip().replace("\n", " ")
    if len(snippet) > 180:
        snippet = snippet[:177] + "..."
    region = packet.region_type or "region"
    return (
        f"- [{packet.packet_id}] page={packet.page} type={region} "
        f"bbox={_fmt_bbox(packet.bbox_norm)} text={snippet!r}"
    )


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
    if isinstance(next_action, str) and next_action in _VALID_NEXT_ACTIONS:
        out["next_action"] = next_action

    confidence = obj.get("confidence")
    if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
        c = float(confidence)
        if 0.0 <= c <= 1.0:
            out["confidence"] = c

    return out
