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


async def answer_from_evidence(
    question: QuestionEvent,
    evidence: EvidenceEvent,
    *,
    backend_client: ModelClient,
) -> tuple[AnswerEvent, ModelResponse]:
    """One VLM call over the packet images. Returns parsed answer + raw response.

    The raw `ModelResponse` comes back alongside the `AnswerEvent` so the
    workflow can attribute tokens and cost to the reasoner step.
    """
    packet_list = "\n".join(
        f"- {p.packet_id}: page {p.page}, bbox {p.bbox_norm}" for p in evidence.packets
    )
    prompt = (
        f"Question: {question.question}\n\n"
        f"Available evidence packets:\n{packet_list}\n\n"
        "Answer using only these packets."
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


def _collect_packet_images(evidence: EvidenceEvent) -> list[Path]:
    """Gather unique local_crop_ref paths in packet order.

    Packets can share a page image (multiple bboxes on the same page). We
    deduplicate while preserving order so the reasoner doesn't see redundant
    attachments.
    """
    seen: set[str] = set()
    images: list[Path] = []
    for p in evidence.packets:
        ref = p.local_crop_ref or p.page_thumbnail_ref
        if not ref or ref in seen:
            continue
        seen.add(ref)
        images.append(Path(ref))
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
