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
    assert "cited_by_answer=yes" in prompt
    assert "cited_by_answer=no" in prompt
    system = client.calls[0]["system"]
    assert "same cited row" in system
    assert "AEC-Q100" in system
    assert "lowest/highest/min/max" in system


async def test_verify_prompt_keeps_enough_table_text_for_math_verdict():
    client = _FakeVerifierClient(
        '{"supported": false, "reason": "math error", '
        '"next_action": "escalate_reasoner", "confidence": 0.8}'
    )
    long_table = (
        "Cash and equivalents $ 12,976 Goodwill 51,001 Intangible assets 21,969 "
        "Other assets 2,503 Long-term debt (2,799) Long-term income taxes (1,946) "
        "Deferred income taxes (4,676) Other liabilities (3,620) Total purchase "
        "price $ 75,408 segment row More Personal Computing acquisitions 51,235"
    )
    await verify_answer(
        _question(domain="finance"),
        _evidence(_packet("pA", snippet=long_table)),
        _answer(answer="84%", citations=["pA"]),
        backend_client=client,
    )

    prompt = client.calls[0]["prompt"]
    assert "Total purchase price $ 75,408" in prompt
    assert "More Personal Computing acquisitions 51,235" in prompt
    assert "Prefer `escalate_reasoner`" in client.calls[0]["system"]


async def test_verify_prompt_focuses_long_packet_text_on_question_terms():
    client = _FakeVerifierClient(
        '{"supported": true, "reason": "ok", "next_action": "accept", "confidence": 0.9}'
    )
    long_table = "\n".join(
        [
            "BCR[22:20] Meaning",
            "b000 IMVA match when BRP is not linked",
            "b001 joint IMVA and context ID match",
            "b010 context ID match",
            "b011 joint IMVA or DMVA and context ID match",
            "b100 IMVA mismatch when BRP is not linked",
            "b101 joint IMVA mismatch and context ID match",
        ]
        + ["filler row"] * 80
    )
    question = _question()
    question.question = "Which BCR[22:20] value means IMVA mismatch when the BRP is not linked?"
    await verify_answer(
        question,
        _evidence(_packet("pA", snippet=long_table)),
        _answer(answer="b100", citations=["pA"]),
        backend_client=client,
    )

    prompt = client.calls[0]["prompt"]
    assert "b100 IMVA mismatch when BRP is not linked" in prompt
    assert "b101 joint IMVA mismatch" in prompt


async def test_verify_prompt_anchors_cited_packet_on_proposed_answer_row():
    client = _FakeVerifierClient(
        '{"supported": true, "reason": "ok", "next_action": "accept", "confidence": 0.9}'
    )
    long_table = "\n".join(
        [
            "BCR[22:20] Meaning",
            "b000 The corresponding BVR is compared against the IMVA bus.",
            "b001 They generate a breakpoint debug event on a joint IMVA and context ID match.",
            "b010 It generates a breakpoint debug event on a context ID match.",
            "b011 They generate a joint IMVA or DMVA and context ID match.",
            "b100 The corresponding BVR is compared against the IMVA bus.",
            "It generates a breakpoint debug event on an IMVA mismatch.",
            "b101 They generate a breakpoint debug event on a joint IMVA mismatch and context ID match.",
        ]
        + ["filler row"] * 120
    )
    question = _question()
    question.question = (
        "Which BCR[22:20] value corresponds to an IMVA mismatch when the BRP is not "
        "linked with context ID linked codes?"
    )
    await verify_answer(
        question,
        _evidence(_packet("pA", snippet=long_table)),
        _answer(answer="b100", citations=["pA"]),
        backend_client=client,
    )

    prompt = client.calls[0]["prompt"]
    assert "b100 The corresponding BVR is compared against the IMVA bus." in prompt
    assert "It generates a breakpoint debug event on an IMVA mismatch." in prompt
    assert prompt.index("b100 The corresponding BVR") < prompt.index("b010 It generates")


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


@pytest.mark.parametrize(
    ("raw_action", "expected"),
    [
        ("Expand_Context", "expand_context"),
        ("expand context.", "expand_context"),
        ("retry-localization", "retry_localization"),
        ("`escalate_reasoner`", "escalate_reasoner"),
    ],
)
async def test_verify_llm_normalizes_common_next_action_variants(raw_action, expected):
    client = _FakeVerifierClient(
        '{"supported": false, "reason": "needs repair", '
        f'"next_action": "{raw_action}", "confidence": 0.7}}'
    )
    verdict, _ = await verify_answer(
        _question(),
        _evidence(_packet()),
        _answer(confidence=0.42),
        backend_client=client,
    )
    assert verdict.supported is False
    assert verdict.next_action == expected


async def test_verify_llm_populates_missing_context_diagnostics():
    client = _FakeVerifierClient(
        '{"supported": false, "reason": "missing legend", '
        '"next_action": "expand_context", "confidence": 0.7, '
        '"diagnostics": {"missing_context": ["footnote", "bogus", "column header"], '
        '"target_packet_ids": ["pkt_000"]}}'
    )
    verdict, _ = await verify_answer(
        _question(),
        _evidence(_packet()),
        _answer(confidence=0.42),
        backend_client=client,
    )
    assert verdict.diagnostics == {
        "missing_context": ["footnote", "column_header", "legend"],
        "target_packet_ids": ["pkt_000"],
    }


async def test_verify_llm_supported_true_forces_accept_action():
    client = _FakeVerifierClient(
        '{"supported": true, "reason": "evidence supports the answer", '
        '"next_action": "escalate_reasoner", "confidence": 0.7}'
    )
    verdict, _ = await verify_answer(
        _question(),
        _evidence(_packet()),
        _answer(confidence=0.42),
        backend_client=client,
    )
    assert verdict.supported is True
    assert verdict.next_action == "accept"
    assert verdict.diagnostics["normalized_next_action"] == "escalate_reasoner"


async def test_verify_llm_supported_false_accept_redirects_to_repair():
    client = _FakeVerifierClient(
        '{"supported": false, "reason": "missing footnote", '
        '"next_action": "accept", "confidence": 0.7}'
    )
    verdict, _ = await verify_answer(
        _question(),
        _evidence(_packet()),
        _answer(confidence=0.42),
        backend_client=client,
    )
    assert verdict.supported is False
    assert verdict.next_action == "expand_context"
    assert verdict.diagnostics["missing_context"] == ["footnote"]
    assert verdict.diagnostics["normalized_next_action"] == "accept"


async def test_verify_llm_infers_missing_context_from_reason():
    client = _FakeVerifierClient(
        '{"supported": false, "reason": "missing legend and footnote; continued table '
        'on next page", "next_action": "expand_context", "confidence": 0.7}'
    )
    verdict, _ = await verify_answer(
        _question(),
        _evidence(_packet()),
        _answer(confidence=0.42),
        backend_client=client,
    )
    assert verdict.diagnostics["missing_context"] == ["footnote", "legend", "continuation"]


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
