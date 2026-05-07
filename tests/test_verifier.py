"""Tests for `focusparse.pipeline.verifier.verify_answer`.

Covers:
  * deterministic fallback when no `backend_client` is provided
  * LLM path with a well-formed JSON reply (all fields flow through)
  * LLM path with a fenced JSON reply
  * LLM path with malformed / non-JSON reply (graceful fallback)
  * invalid `next_action` is rejected
  * invalid `supported` type is rejected
  * out-of-range `confidence` is rejected
  * reason trimmed to 240 chars
  * token/usd telemetry comes back on the ModelResponse
  * packet summaries make it into the prompt

No parser-bench submodule required — events + EvidencePacket are pydantic-only.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from focusparse.evidence.packet import CropRef, EvidencePacket, PacketProvenance
from focusparse.models.base import ModelResponse
from focusparse.pipeline.events import (
    AnswerEvent,
    EvidenceEvent,
    QuestionEvent,
)
from focusparse.pipeline.verifier import verify_answer


class _FakeVerifierClient:
    def __init__(self, text: str, *, tokens_in: int = 120, tokens_out: int = 30) -> None:
        self._text = text
        self._tokens_in = tokens_in
        self._tokens_out = tokens_out
        self.calls: list[dict] = []

    async def predict(
        self,
        prompt: str,
        images: list[Path] | None = None,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        self.calls.append({"prompt": prompt, "system": system})
        return ModelResponse(
            text=self._text,
            tokens_in=self._tokens_in,
            tokens_out=self._tokens_out,
            usd=0.0002,
            latency_ms=55,
        )

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)


def _question(domain: str | None = None) -> QuestionEvent:
    return QuestionEvent(
        example_id="ex-1",
        question="What is the max supply voltage on the MCU?",
        doc_id="datasheet-A",
        pages_available=10,
        domain=domain,
    )


def _packet(
    packet_id: str = "p1", *, page: int = 3, snippet: str = "VCC max 3.6 V"
) -> EvidencePacket:
    return EvidencePacket(
        packet_id=packet_id,
        page=page,
        bbox_norm=(0.1, 0.2, 0.4, 0.3),
        region_type="table",
        page_thumbnail_ref=f"thumb-{packet_id}",
        local_crop_ref=f"crop-{packet_id}",
        ocr_snippet=snippet,
        provenance=PacketProvenance(tool="skeleton_inspector", args_hash="abc"),
    )


def _answer(
    answer: str = "3.6 V",
    citations: list[str] | None = None,
    confidence: float = 0.7,
) -> AnswerEvent:
    return AnswerEvent(
        answer=answer,
        citations=citations if citations is not None else ["p1"],
        confidence=confidence,
    )


def _evidence(*packets: EvidencePacket) -> EvidenceEvent:
    return EvidenceEvent(packets=list(packets))


# ---------------------------------------------------------------------------
# Deterministic fallback
# ---------------------------------------------------------------------------


async def test_verify_no_client_accepts_with_answer_confidence():
    verdict, response = await verify_answer(
        _question(), _evidence(_packet()), _answer(confidence=0.42)
    )
    assert response is None
    assert verdict.supported is True
    assert verdict.next_action == "accept"
    assert verdict.reason == "skeleton_always_accept"
    assert verdict.confidence == 0.42


async def test_verify_no_client_with_empty_evidence():
    verdict, response = await verify_answer(_question(), _evidence(), _answer(citations=[]))
    assert response is None
    assert verdict.supported is True
    assert verdict.next_action == "accept"


# ---------------------------------------------------------------------------
# LLM path — happy case
# ---------------------------------------------------------------------------


async def test_verify_llm_happy_path_fills_all_fields():
    client = _FakeVerifierClient(
        '{"supported": true, "reason": "cited packet p1 contains '
        'the VCC max row explicitly", "next_action": "accept", '
        '"confidence": 0.88}'
    )
    verdict, response = await verify_answer(
        _question(domain="datasheet"),
        _evidence(_packet()),
        _answer(),
        backend_client=client,
    )
    assert response is not None
    assert response.tokens_in == 120
    assert response.tokens_out == 30
    assert verdict.supported is True
    assert verdict.next_action == "accept"
    assert "cited packet p1" in verdict.reason
    assert verdict.confidence == 0.88
    assert len(client.calls) == 1


async def test_verify_llm_accepts_fenced_json():
    client = _FakeVerifierClient(
        "Here is the verdict:\n"
        "```json\n"
        '{"supported": false, "reason": "bbox covers the wrong row", '
        '"next_action": "retry_localization", "confidence": 0.65}\n'
        "```"
    )
    verdict, _ = await verify_answer(
        _question(),
        _evidence(_packet()),
        _answer(),
        backend_client=client,
    )
    assert verdict.supported is False
    assert verdict.next_action == "retry_localization"
    assert verdict.confidence == 0.65


async def test_verify_llm_emits_expand_context_for_missing_neighbor():
    client = _FakeVerifierClient(
        '{"supported": false, "reason": "table row has a footnote ref '
        'not in evidence", "next_action": "expand_context", '
        '"confidence": 0.55}'
    )
    verdict, _ = await verify_answer(
        _question(),
        _evidence(_packet()),
        _answer(),
        backend_client=client,
    )
    assert verdict.next_action == "expand_context"


async def test_verify_prompt_includes_packet_summary_and_citations():
    client = _FakeVerifierClient(
        '{"supported": true, "reason": "ok", "next_action": "accept", "confidence": 0.9}'
    )
    packets = (
        _packet("pA", page=3, snippet="VCC max 3.6 V"),
        _packet("pB", page=5, snippet="Conditions apply"),
    )
    await verify_answer(
        _question(domain="datasheet"),
        _evidence(*packets),
        _answer(citations=["pA"]),
        backend_client=client,
    )
    prompt = client.calls[0]["prompt"]
    assert "pA" in prompt
    assert "pB" in prompt
    assert "VCC max 3.6 V" in prompt
    assert "datasheet" in prompt
    # reasoner's answer + cited packet_ids are visible.
    assert "3.6 V" in prompt
    assert "pA" in prompt


async def test_verify_prompt_summarizes_multi_scale_chart_context():
    client = _FakeVerifierClient(
        '{"supported": true, "reason": "ok", "next_action": "accept", "confidence": 0.9}'
    )
    packet = _packet("pA")
    packet.multi_scale_crops = [
        CropRef(ref="/tight.png", bbox_norm=(0.1, 0.2, 0.4, 0.3), scale="tight"),
        CropRef(ref="/chart.png", bbox_norm=(0.0, 0.1, 0.6, 0.5), scale="chart_context"),
    ]
    await verify_answer(
        _question(domain="datasheet"),
        _evidence(packet),
        _answer(citations=["pA"]),
        backend_client=client,
    )
    prompt = client.calls[0]["prompt"]
    assert "scales=[tight:[0.100, 0.200, 0.400, 0.300]" in prompt
    assert "chart_context:[0.000, 0.100, 0.600, 0.500]" in prompt


# ---------------------------------------------------------------------------
# LLM path — defensive fallback
# ---------------------------------------------------------------------------


async def test_verify_llm_non_json_falls_back_but_returns_response():
    client = _FakeVerifierClient("I think the answer looks fine.")
    verdict, response = await verify_answer(
        _question(),
        _evidence(_packet()),
        _answer(confidence=0.42),
        backend_client=client,
    )
    # Response still propagates for telemetry...
    assert response is not None
    # ...but every field fell back.
    assert verdict.supported is True
    assert verdict.next_action == "accept"
    assert verdict.reason == "skeleton_always_accept"
    assert verdict.confidence == 0.42


async def test_verify_llm_rejects_invalid_next_action():
    client = _FakeVerifierClient(
        '{"supported": true, "reason": "ok", "next_action": "nuke_from_orbit", "confidence": 0.9}'
    )
    verdict, _ = await verify_answer(
        _question(),
        _evidence(_packet()),
        _answer(confidence=0.42),
        backend_client=client,
    )
    # supported + confidence + reason survive; only next_action falls back.
    assert verdict.supported is True
    assert verdict.confidence == 0.9
    assert verdict.next_action == "accept"
    assert verdict.reason == "ok"


async def test_verify_llm_rejects_non_bool_supported():
    client = _FakeVerifierClient(
        '{"supported": "yes", "reason": "ok", "next_action": "accept", "confidence": 0.9}'
    )
    verdict, _ = await verify_answer(
        _question(),
        _evidence(_packet()),
        _answer(confidence=0.42),
        backend_client=client,
    )
    # supported fell back; the rest survived.
    assert verdict.supported is True  # fallback
    assert verdict.next_action == "accept"
    assert verdict.confidence == 0.9


async def test_verify_llm_rejects_out_of_range_confidence():
    client = _FakeVerifierClient(
        '{"supported": true, "reason": "ok", "next_action": "accept", "confidence": 1.5}'
    )
    verdict, _ = await verify_answer(
        _question(),
        _evidence(_packet()),
        _answer(confidence=0.42),
        backend_client=client,
    )
    # Confidence fell back to the answer's confidence.
    assert verdict.confidence == 0.42


async def test_verify_llm_trims_long_reason():
    long_reason = "x" * 500
    client = _FakeVerifierClient(
        '{"supported": true, "reason": "'
        + long_reason
        + '", "next_action": "accept", "confidence": 0.9}'
    )
    verdict, _ = await verify_answer(
        _question(),
        _evidence(_packet()),
        _answer(),
        backend_client=client,
    )
    assert len(verdict.reason) == 240


async def test_verify_llm_supported_false_propagates():
    # Regression: `False` is falsy, earlier drafts used `parsed.get("supported")
    # or fallback.supported` which would silently flip False→True.
    client = _FakeVerifierClient(
        '{"supported": false, "reason": "evidence contradicts answer", '
        '"next_action": "abstain", "confidence": 0.8}'
    )
    verdict, _ = await verify_answer(
        _question(),
        _evidence(_packet()),
        _answer(),
        backend_client=client,
    )
    assert verdict.supported is False
    assert verdict.next_action == "abstain"


@pytest.mark.parametrize(
    "bad_payload",
    [
        "",
        "not json at all",
        '{"supported":}',
        "[1, 2, 3]",
    ],
)
async def test_verify_llm_robust_to_bad_payloads(bad_payload):
    client = _FakeVerifierClient(bad_payload)
    verdict, response = await verify_answer(
        _question(),
        _evidence(_packet()),
        _answer(),
        backend_client=client,
    )
    assert response is not None
    assert verdict.supported is True
    assert verdict.next_action == "accept"
    assert verdict.reason == "skeleton_always_accept"
