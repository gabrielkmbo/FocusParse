"""ANSWER stage — frontier-tier reasoner sees ONLY EvidencePackets.

Never the full document. The reasoner is handed one image per packet plus a
prompt that enumerates packet ids; it emits `{answer, citations, confidence}`
where citations are packet-id strings the verifier can look up.

Phase 2 skeleton: single-shot call. Sub-phase 2f adds K=2 self-consistency
sampling + escalation wiring.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from focusparse.models.base import ModelClient, ModelResponse
from focusparse.pipeline.events import AnswerEvent, EvidenceEvent, QuestionEvent

_SYSTEM_PROMPT = (
    "You are answering a question about a document using the provided evidence packets. "
    "Each packet shows a page region with a packet_id (e.g. pkt_000). "
    "Return strict JSON with keys `answer`, `citations`, and `confidence`. "
    "`answer` is the answer string (or the literal word 'Unanswerable'). "
    "`citations` is a list of packet_id strings that directly support the answer. "
    "`confidence` is a float in [0,1]. Do not add extra keys."
)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _format_hint(answer_type: str | None) -> str:
    """Mirror of `workflow._format_hint`. Kept local to avoid a workflow import
    cycle (reasoner is imported by workflow). Type-aware nudges so the model
    emits scorer-compliant output instead of prose."""
    if not answer_type:
        return ""
    s = str(answer_type)
    stem = s.split(".")[-1].lower() if "." in s else s.lower()
    if stem == "numeric":
        return (
            "Answer with a single number. If the question asks for a percentage, "
            "include the % sign. Do not add explanations or units beyond what the "
            "question asks for."
        )
    if stem == "exact_match":
        return (
            "Answer with the exact label, identifier, or phrase from the document. "
            "Quote the document verbatim — do not paraphrase, abbreviate, or add "
            "explanation text that isn't present in the document. Match the "
            "document's exact punctuation."
        )
    if stem == "boolean":
        return "Answer 'yes' or 'no'."
    if stem == "multiple_choice":
        return "Answer with the letter of the correct choice (A, B, C, ...)."
    if stem == "unanswerable":
        return "If the document does not contain the answer, reply 'Unanswerable'."
    return ""


async def answer_from_evidence(
    question: QuestionEvent,
    evidence: EvidenceEvent,
    *,
    backend_client: ModelClient,
    escalation_hint: str | None = None,
) -> tuple[AnswerEvent, ModelResponse]:
    """One VLM call over the packet images. Returns parsed answer + raw response.

    The raw `ModelResponse` comes back alongside the `AnswerEvent` so the
    workflow can attribute tokens and cost to the reasoner step.

    `escalation_hint`, when provided, is prepended to the prompt as the
    verifier's reason for rejecting the previous answer. This is how the
    `verifier→retry→escalate_reasoner` control-flow loop tells the
    reasoner "your last try was unsupported; here's why" without changing
    the evidence packets. Pass it from the workflow's retry handler; pass
    None for first-attempt and routine answer calls.
    """
    packet_list = "\n".join(_render_packet_line(p) for p in evidence.packets)
    hint_block = ""
    if escalation_hint:
        hint_block = (
            "Your previous answer was rejected by the verifier with this reason:\n"
            f"{escalation_hint}\n\n"
            "Re-read the evidence packets carefully and produce an answer that "
            "addresses the verifier's concern.\n\n"
        )
    format_hint = _format_hint(question.answer_type)
    format_block = f"\n{format_hint}\n" if format_hint else ""
    prompt = (
        f"{hint_block}"
        f"Question: {question.question}\n\n"
        f"Available evidence packets:\n{packet_list}\n\n"
        f"Answer using only these packets.{format_block}"
    )
    images = _collect_packet_images(evidence)

    response = await backend_client.predict(
        prompt=prompt,
        images=images,
        system=_SYSTEM_PROMPT,
    )

    answer, citations, confidence = _parse_reasoner_response(
        response.text,
        valid_packet_ids={p.packet_id for p in evidence.packets},
    )
    return (
        AnswerEvent(
            answer=answer,
            citations=citations,
            confidence=confidence,
            reasoning_summary=None,
        ),
        response,
    )


def _render_packet_line(packet) -> str:
    """One descriptor line for a packet in the reasoner's prompt.

    Sprint Phase 2: multi_scale_crops annotation tells the reasoner how
    many image scales it will see (tight + context).
    Sprint Phase 3: when chart_csv is populated, the reasoner sees a
    code-fenced CSV block beneath the descriptor so axis-value
    interpolation questions land on hard data instead of guesses.
    """
    base = f"- {packet.packet_id}: page {packet.page}, bbox {packet.bbox_norm}"
    n_scales = len(packet.multi_scale_crops)
    if n_scales >= 2:
        base += f" — {n_scales} image scales (tight + context)"
    if packet.chart_csv:
        conf = packet.chart_extraction_confidence
        conf_str = f" (confidence={conf:.2f})" if conf is not None else ""
        base += (
            f"\n  Chart extraction{conf_str} — treat as advisory; "
            "verify against the crop:\n  ```csv\n  "
            + "\n  ".join(packet.chart_csv.splitlines())
            + "\n  ```"
        )
    return base


def _collect_packet_images(evidence: EvidenceEvent) -> list[Path]:
    """Gather unique crop_ref paths in packet order.

    Packets can share a page image (multiple bboxes on the same page). We
    deduplicate while preserving order so the reasoner doesn't see redundant
    attachments.

    Sprint Phase 2 (2026-05-04, Phase 6 #6): when a packet has
    `multi_scale_crops` populated (tight + context), enumerate every
    scale's ref. Falls back to the legacy local_crop_ref / page_thumbnail
    chain for packets without multi-scale.

    Path A (2026-05-06): after the primary crop(s), enumerate the packet's
    `linked_crop_refs` (neighbors attached by `expand_context` — captions,
    footnotes, section headers, etc.). Pre-Path-A, these were populated
    on the packet but never reached the reasoner. The 2026-05-06 memory
    entry documents the dead-code finding that motivated this change.
    """
    seen: set[str] = set()
    images: list[Path] = []
    for p in evidence.packets:
        if p.multi_scale_crops:
            for scaled in p.multi_scale_crops:
                ref = scaled.ref
                if not ref or ref in seen:
                    continue
                seen.add(ref)
                images.append(Path(ref))
        else:
            ref = p.local_crop_ref or p.page_thumbnail_ref
            if ref and ref not in seen:
                seen.add(ref)
                images.append(Path(ref))
        # Linked neighbor crops follow the primary crop(s) so the prompt
        # ordering matches "primary first, then context."
        for neighbor_ref in p.linked_crop_refs or []:
            if not neighbor_ref or neighbor_ref in seen:
                continue
            seen.add(neighbor_ref)
            images.append(Path(neighbor_ref))
    return images


def _parse_reasoner_response(
    text: str,
    *,
    valid_packet_ids: set[str],
) -> tuple[str, list[str], float]:
    """Extract (answer, citations, confidence). Tolerant of fence / prefix noise."""
    if not text:
        return "", [], 0.0

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
        return text.strip(), [], 0.0

    if not isinstance(obj, dict):
        return text.strip(), [], 0.0

    answer = obj.get("answer", "")
    if not isinstance(answer, str):
        answer = str(answer)

    raw_citations = obj.get("citations", []) or []
    citations = [c for c in raw_citations if isinstance(c, str) and c in valid_packet_ids]

    confidence_raw = obj.get("confidence", 0.5)
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    return answer, citations, confidence
