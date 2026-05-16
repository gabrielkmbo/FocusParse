"""Workflow skeleton tests — Phase 2 sub-phases 2a+2b.

Two layers of coverage:

1. **Pure helpers** (no submodule required): `_images_by_page`,
   `_page_number_from_filename`, `_citations_from_packets`,
   `_infer_doc_id`, and parser-agnostic checks on `_parse_simple_response`.

2. **End-to-end FocusWorkflow.run**: uses a `_FakeClient` for the reasoner
   call + a real `BenchmarkExample` (gated on parser-bench submodule).
   Asserts:
     - exactly 7 TrajectoryStep records (one per @step)
     - one LLM call hits the reasoner
     - citations resolve back to {page, bbox}
     - bad packet_ids are silently dropped
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from focusparse.evidence.packet import EvidencePacket, PacketProvenance
from focusparse.models.base import ModelResponse
from focusparse.pipeline.events import AnswerEvent, EvidenceEvent, QuestionEvent, VerdictEvent
from focusparse.pipeline.workflow import (
    FocusWorkflow,
    SimpleBaselineAgent,
    WorkflowResult,
    _build_reasoner_repair_hint,
    _citations_from_packets,
    _focused_retry_evidence,
    _images_by_page,
    _infer_doc_id,
    _is_better_unsupported_answer,
    _maybe_accept_deterministic_finance_answer,
    _page_number_from_filename,
    _should_allow_reasoner_shape_retry,
    _should_use_react_inspector,
    _verifier_requests_visual_readability_retry,
    _verifier_target_packet_ids,
)

# ---------------------------------------------------------------------------
# Import-graph sanity (cheap regression catches)
# ---------------------------------------------------------------------------


def test_event_imports():
    from focusparse.pipeline.events import (
        AnswerEvent,
        EvidenceEvent,
        PagesEvent,
        PlanEvent,
        QuestionEvent,
        RegionsEvent,
        VerdictEvent,
    )

    assert QuestionEvent.__name__ == "QuestionEvent"
    assert all(
        e is not None
        for e in (PlanEvent, PagesEvent, RegionsEvent, EvidenceEvent, AnswerEvent, VerdictEvent)
    )


def test_workflow_stub_importable():
    assert FocusWorkflow.__name__ == "FocusWorkflow"
    assert SimpleBaselineAgent.__name__ == "SimpleBaselineAgent"
    assert WorkflowResult is not None


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("datasheet-A_page_0003_300dpi.png", 3),
        ("something_page_0010_150dpi.png", 10),
        ("no_page_number_here.png", None),
        ("page_3.png", None),  # pattern requires leading underscore
    ],
)
def test_page_number_from_filename(name, expected):
    assert _page_number_from_filename(name) == expected


def test_images_by_page_uses_filename_first():
    imgs = [
        Path("data/processed/datasheet-A/images/datasheet-A_page_0003_300dpi.png"),
        Path("data/processed/datasheet-A/images/datasheet-A_page_0007_300dpi.png"),
    ]
    mapping = _images_by_page(example=None, images=imgs)  # example unused by helper
    assert set(mapping.keys()) == {3, 7}
    assert mapping[3].name == "datasheet-A_page_0003_300dpi.png"


def test_images_by_page_falls_back_to_positional_index():
    imgs = [Path("no_page_here_a.png"), Path("no_page_here_b.png")]
    mapping = _images_by_page(example=None, images=imgs)
    # Fallback: idx+1 -> 1, 2
    assert mapping[1].name == "no_page_here_a.png"
    assert mapping[2].name == "no_page_here_b.png"


def test_citations_from_packets_translates_packet_ids_to_bbox_dicts():
    packets = [
        _make_packet(packet_id="pkt_000", page=3, bbox=(0.1, 0.2, 0.3, 0.4)),
        _make_packet(packet_id="pkt_001", page=5, bbox=(0.5, 0.6, 0.7, 0.8)),
    ]
    cites = _citations_from_packets(["pkt_000", "pkt_001"], packets)
    assert cites == [
        {"page": 3, "bbox": [0.1, 0.2, 0.3, 0.4]},
        {"page": 5, "bbox": [0.5, 0.6, 0.7, 0.8]},
    ]


def test_citations_from_packets_silently_drops_unknown_refs():
    packets = [_make_packet(packet_id="pkt_000", page=1, bbox=(0, 0, 1, 1))]
    cites = _citations_from_packets(["pkt_000", "pkt_999", "garbage"], packets)
    assert len(cites) == 1
    assert cites[0]["page"] == 1


def test_citations_from_packets_empty_list_yields_empty():
    assert _citations_from_packets([], []) == []


def test_verifier_target_packet_ids_normalizes_diagnostics_and_prose():
    from focusparse.pipeline.events import VerdictEvent

    verdict = VerdictEvent(
        supported=False,
        reason="Packet 003 still needs the legend; pkt-004 has the table header.",
        next_action="expand_context",
        confidence=0.6,
        diagnostics={"target_packet_ids": ["003", "Packet pkt_002", "pkt_999"]},
    )

    assert _verifier_target_packet_ids(
        verdict,
        valid_packet_ids={"pkt_002", "pkt_003", "pkt_004"},
    ) == ["pkt_003", "pkt_002", "pkt_004"]


def test_verifier_visual_readability_retry_requires_precise_signal():
    from focusparse.pipeline.events import VerdictEvent

    verdict = VerdictEvent(
        supported=False,
        reason="pkt_000 crop is blurry and the axis label is unreadable",
        next_action="expand_context",
        confidence=0.6,
    )
    assert _verifier_requests_visual_readability_retry(verdict, target_packet_ids=["pkt_000"])

    fragmented_chart = verdict.model_copy(
        update={
            "reason": (
                "The OCR text from pkt_001 is too fragmented and unclear to reliably "
                "read the chart structure."
            )
        }
    )
    assert _verifier_requests_visual_readability_retry(
        fragmented_chart,
        target_packet_ids=["pkt_001"],
    )

    diagram = verdict.model_copy(update={"reason": "pkt_000 diagram text is garbled/unreadable"})
    assert _verifier_requests_visual_readability_retry(diagram, target_packet_ids=["pkt_000"])

    missing_neighbor = verdict.model_copy(
        update={
            "reason": "pkt_000 needs the legend",
            "diagnostics": {"missing_context": ["legend"]},
        }
    )
    assert not _verifier_requests_visual_readability_retry(
        missing_neighbor,
        target_packet_ids=["pkt_000"],
    )

    vague = verdict.model_copy(update={"reason": "pkt_000 needs the legend"})
    assert not _verifier_requests_visual_readability_retry(vague, target_packet_ids=["pkt_000"])


def test_focused_retry_keeps_same_page_cited_explanatory_context():
    target = EvidencePacket(
        packet_id="pkt_000",
        page=2,
        bbox_norm=(0.10, 0.20, 0.40, 0.50),
        region_type="figure",
        page_thumbnail_ref="/tmp/page.png",
        local_crop_ref="/tmp/figure.png",
        provenance=PacketProvenance(tool="test", args_hash="target"),
    )
    explanatory = EvidencePacket(
        packet_id="pkt_002",
        page=2,
        bbox_norm=(0.10, 0.55, 0.70, 0.65),
        region_type="text",
        text_layer_snippet="Use IOUT at the OUT terminal, not VRECT.",
        page_thumbnail_ref="/tmp/page.png",
        local_crop_ref="/tmp/text.png",
        provenance=PacketProvenance(tool="test", args_hash="text"),
    )
    other_page = EvidencePacket(
        packet_id="pkt_003",
        page=3,
        bbox_norm=(0.10, 0.20, 0.40, 0.50),
        region_type="text",
        text_layer_snippet="Wrong page",
        page_thumbnail_ref="/tmp/page3.png",
        local_crop_ref="/tmp/text3.png",
        provenance=PacketProvenance(tool="test", args_hash="other"),
    )

    out = _focused_retry_evidence(
        EvidenceEvent(packets=[target, explanatory, other_page]),
        ["pkt_000"],
        cited_packet_ids=["pkt_000", "pkt_002", "pkt_003"],
    )

    assert [packet.packet_id for packet in out.packets] == ["pkt_000", "pkt_002"]


def test_focused_retry_keeps_visual_subpanels_for_overview_retry():
    overview = EvidencePacket(
        packet_id="pkt_000",
        page=19,
        bbox_norm=(0.05, 0.10, 0.95, 0.90),
        region_type="Picture",
        page_thumbnail_ref="/tmp/page.png",
        local_crop_ref="/tmp/overview.png",
        provenance=PacketProvenance(tool="test", args_hash="overview"),
    )
    subpanel = EvidencePacket(
        packet_id="pkt_007",
        page=19,
        bbox_norm=(0.50, 0.15, 0.90, 0.35),
        region_type="Picture",
        ocr_snippet="PGOOD CH1 Time (5us/Div)",
        page_thumbnail_ref="/tmp/page.png",
        local_crop_ref="/tmp/subpanel.png",
        provenance=PacketProvenance(tool="test", args_hash="subpanel"),
    )
    far_visual = EvidencePacket(
        packet_id="pkt_003",
        page=20,
        bbox_norm=(0.50, 0.15, 0.90, 0.35),
        region_type="Picture",
        page_thumbnail_ref="/tmp/page20.png",
        local_crop_ref="/tmp/far.png",
        provenance=PacketProvenance(tool="test", args_hash="far"),
    )
    text_packet = EvidencePacket(
        packet_id="pkt_004",
        page=19,
        bbox_norm=(0.50, 0.15, 0.90, 0.35),
        region_type="Text",
        text_layer_snippet="not a visual subpanel",
        page_thumbnail_ref="/tmp/page.png",
        local_crop_ref="/tmp/text.png",
        provenance=PacketProvenance(tool="test", args_hash="text"),
    )

    out = _focused_retry_evidence(
        EvidenceEvent(packets=[overview, subpanel, far_visual, text_packet]),
        ["pkt_000"],
        cited_packet_ids=["pkt_000"],
        verifier_reason=(
            "Packet pkt_000 is a layout overview containing multiple waveforms, "
            "not a clear oscilloscope trace with visible gridlines."
        ),
    )

    assert [packet.packet_id for packet in out.packets] == ["pkt_000", "pkt_007"]


def test_retry_answer_selector_allows_question_specific_fix_within_margin():
    incumbent = AnswerEvent(answer="G = 24", citations=["pkt_000"], confidence=0.87)
    candidate = AnswerEvent(answer="Gain = 24", citations=["pkt_000"], confidence=0.81)

    assert _is_better_unsupported_answer(
        candidate,
        incumbent,
        question_text="Which gain setting has the highest response?",
    )


def test_retry_answer_selector_keeps_higher_confidence_when_overlap_ties():
    incumbent = AnswerEvent(answer="4 µs", citations=["pkt_000"], confidence=0.74)
    candidate = AnswerEvent(answer="8 µs", citations=["pkt_000"], confidence=0.64)

    assert not _is_better_unsupported_answer(
        candidate,
        incumbent,
        question_text="What is the C2V hold time?",
    )


def test_retry_answer_selector_prefers_single_entity_fix_within_margin():
    incumbent = AnswerEvent(answer="UK and US", citations=["pkt_000"], confidence=0.89)
    candidate = AnswerEvent(answer="Germany", citations=["pkt_003"], confidence=0.75)

    assert _is_better_unsupported_answer(
        candidate,
        incumbent,
        question_text=(
            "Based on the charts and the footnote, which country's 10-year government "
            "bond yield showed the least change?"
        ),
    )


def test_retry_answer_selector_prefers_concise_variable_answer():
    incumbent = AnswerEvent(
        answer="P RX,AC = (V RECT x I OUT ) / Eff RECT + P res_loss + P offset",
        citations=["pkt_003"],
        confidence=0.96,
    )
    candidate = AnswerEvent(answer="I OUT", citations=["pkt_003"], confidence=0.80)

    assert _is_better_unsupported_answer(
        candidate,
        incumbent,
        question_text=(
            "Which Y-axis variable, VRECT or IOUT, should be used to calculate output power at OUT?"
        ),
    )


def test_retry_answer_selector_prefers_variable_over_descriptive_fragment():
    incumbent = AnswerEvent(
        answer="IOUT is the output current from ADC",
        citations=["pkt_003"],
        confidence=0.85,
    )
    candidate = AnswerEvent(answer="IOUT", citations=["pkt_000", "pkt_003"], confidence=0.82)

    assert _is_better_unsupported_answer(
        candidate,
        incumbent,
        question_text=(
            "Which Y-axis variable, VRECT or IOUT, should be used to calculate output power at OUT?"
        ),
    )


def test_variable_question_allows_reasoner_shape_retry():
    verdict = VerdictEvent(
        supported=False,
        reason=(
            "The reasoner did not answer the actual question, which asks which "
            "Y-axis variable should be used."
        ),
        next_action="escalate_reasoner",
        confidence=0.75,
    )
    answer = AnswerEvent(
        answer="P RX,AC = (V RECT x I OUT ) / Eff RECT + P res_loss + P offset",
        citations=["pkt_003"],
        confidence=0.95,
    )
    question = QuestionEvent(
        example_id="ex",
        question="Which Y-axis variable, VRECT or IOUT, should be used?",
        doc_id="doc",
        pages_available=1,
        answer_type="exact_match",
    )

    assert _should_allow_reasoner_shape_retry(
        action="escalate_reasoner",
        answer=answer,
        verdict=verdict,
        question_event=question,
        max_evidence_retries=1,
    )


def test_verbose_numeric_answer_allows_reasoner_shape_retry():
    verdict = VerdictEvent(
        supported=False,
        reason="The answer is too verbose and does not directly provide the scalar value.",
        next_action="escalate_reasoner",
        confidence=0.75,
    )
    answer = AnswerEvent(
        answer=(
            'You might incorrectly report "10%", but the table note shows that '
            "the requested percentage should be reported as 0%."
        ),
        citations=["pkt_003"],
        confidence=0.72,
    )
    question = QuestionEvent(
        example_id="ex",
        question="What percentage should be reported for the prior-period adjustment?",
        doc_id="doc",
        pages_available=1,
        answer_type="numeric",
    )

    assert _should_allow_reasoner_shape_retry(
        action="escalate_reasoner",
        answer=answer,
        verdict=verdict,
        question_event=question,
        max_evidence_retries=1,
    )


def test_contract_diagnostic_allows_reasoner_shape_retry():
    verdict = VerdictEvent(
        supported=False,
        reason="The proposed answer violates the question answer contract.",
        next_action="escalate_reasoner",
        confidence=0.75,
        diagnostics={"answer_shape_failure": ["missing_field"]},
    )
    answer = AnswerEvent(answer="0.697", citations=["pkt_003"], confidence=0.72)
    question = QuestionEvent(
        example_id="ex",
        question=(
            "Which value (min, typ, or max) should be used, and what is the corresponding voltage?"
        ),
        doc_id="doc",
        pages_available=1,
        answer_type="exact_match",
    )

    assert _should_allow_reasoner_shape_retry(
        action="escalate_reasoner",
        answer=answer,
        verdict=verdict,
        question_event=question,
        max_evidence_retries=1,
    )


def test_checkbox_diagnostic_allows_reasoner_shape_retry():
    verdict = VerdictEvent(
        supported=False,
        reason="The checkbox mark is bound to the wrong adjacent label.",
        next_action="escalate_reasoner",
        confidence=0.75,
        diagnostics={"answer_shape_failure": ["checkbox_binding_risk"]},
    )
    answer = AnswerEvent(answer="no", citations=["pkt_003"], confidence=0.72)
    question = QuestionEvent(
        example_id="ex",
        question="Based on the check marks, did the registrant file all required reports?",
        doc_id="doc",
        pages_available=1,
        answer_type="boolean",
    )

    assert _should_allow_reasoner_shape_retry(
        action="escalate_reasoner",
        answer=answer,
        verdict=verdict,
        question_event=question,
        max_evidence_retries=1,
    )


def test_reasoner_repair_hint_targets_corresponding_row_adjudication():
    verdict = VerdictEvent(
        supported=False,
        reason="The answer chose the output-field minimum instead of the corresponding row.",
        next_action="escalate_reasoner",
        confidence=0.75,
        diagnostics={
            "answer_shape_failure": ["wrong_row_risk"],
            "corresponding_row_binding_cues": ["source_row", "output_field"],
        },
    )
    answer = AnswerEvent(answer="169,148; minimum", citations=["pkt_003"], confidence=0.72)
    question = QuestionEvent(
        example_id="ex",
        question=(
            "For the year in which Products net sales reached their minimum among the "
            "three years shown, what was the corresponding Gross margin value?"
        ),
        doc_id="doc",
        pages_available=1,
        answer_type="exact_match",
    )
    evidence = EvidenceEvent(
        packets=[
            EvidencePacket(
                packet_id="pkt_003",
                page=1,
                bbox_norm=(0.1, 0.1, 0.8, 0.8),
                page_thumbnail_ref="/tmp/page.png",
                local_crop_ref="/tmp/crop.png",
                text_layer_snippet=(
                    "Products net sales 297,392 220,747 198,270\n"
                    "Services net sales 96,169 85,200 78,129\n"
                    "Gross margin 169,148 180,683 170,782"
                ),
                provenance=PacketProvenance(tool="test", args_hash=""),
            )
        ]
    )

    hint = _build_reasoner_repair_hint(
        verdict,
        answer_event=answer,
        question_event=question,
        evidence=evidence,
    )

    assert "Previous answer: 169,148; minimum" in hint
    assert "Previous cited packet_ids: pkt_003" in hint
    assert "Targeted corresponding-row repair" in hint
    assert "Same-evidence repair context" in hint
    assert "Products net sales" in hint
    assert "Gross margin" in hint
    assert "Services net sales" not in hint
    assert "Adjudicate candidates internally" in hint
    assert "Same-evidence repair worksheet" in hint
    assert "Candidate A = previous answer" in hint
    assert "nearby confusable row/entity" in hint


def test_reasoner_repair_hint_targets_checkbox_binding():
    verdict = VerdictEvent(
        supported=False,
        reason="The checkbox mark is bound to the wrong adjacent label.",
        next_action="escalate_reasoner",
        confidence=0.75,
        diagnostics={"answer_shape_failure": ["checkbox_binding_risk"]},
    )
    answer = AnswerEvent(answer="no", citations=["pkt_003"], confidence=0.72)
    question = QuestionEvent(
        example_id="ex",
        question="Based on the check marks, did the registrant file all required reports?",
        doc_id="doc",
        pages_available=1,
        answer_type="boolean",
    )
    evidence = EvidenceEvent(
        packets=[
            EvidencePacket(
                packet_id="pkt_003",
                page=1,
                bbox_norm=(0.1, 0.1, 0.8, 0.8),
                page_thumbnail_ref="/tmp/page.png",
                local_crop_ref="/tmp/crop.png",
                text_layer_snippet=(
                    "Large accelerated filer Yes [X] No [ ]\n"
                    "Filed all required reports Yes [X] No [ ]"
                ),
                provenance=PacketProvenance(tool="test", args_hash=""),
            )
        ]
    )

    hint = _build_reasoner_repair_hint(
        verdict,
        answer_event=answer,
        question_event=question,
        evidence=evidence,
    )

    assert "Previous answer: no" in hint
    assert "Targeted checkbox repair" in hint
    assert "Same-evidence repair context" in hint
    assert "Filed all required reports Yes [X] No [ ]" in hint
    assert "nearest Yes/No" in hint
    assert "Candidate B = checkbox marks bound to nearest labels" in hint
    assert "alternate Yes/No binding" in hint


def test_concise_exact_answer_blocks_reasoner_shape_retry():
    verdict = VerdictEvent(
        supported=False,
        reason="The verifier thinks the answer misread the cited table cell.",
        next_action="escalate_reasoner",
        confidence=0.75,
    )
    answer = AnswerEvent(answer="ADRV9040_FW.bin", citations=["pkt_003"], confidence=0.72)
    question = QuestionEvent(
        example_id="ex",
        question="What firmware file is loaded?",
        doc_id="doc",
        pages_available=1,
        answer_type="exact_match",
    )

    assert not _should_allow_reasoner_shape_retry(
        action="escalate_reasoner",
        answer=answer,
        verdict=verdict,
        question_event=question,
        max_evidence_retries=1,
    )


def test_boolean_answer_blocks_verbose_reasoner_shape_retry():
    verdict = VerdictEvent(
        supported=False,
        reason="The answer is verbose and does not directly answer the question.",
        next_action="escalate_reasoner",
        confidence=0.75,
    )
    answer = AnswerEvent(
        answer="No, VOUT2 does not dip below the LDO threshold in the timing waveform.",
        citations=["pkt_003"],
        confidence=0.72,
    )
    question = QuestionEvent(
        example_id="ex",
        question="Does VOUT2 dip below the LDO threshold?",
        doc_id="doc",
        pages_available=1,
        answer_type="boolean",
    )

    assert not _should_allow_reasoner_shape_retry(
        action="escalate_reasoner",
        answer=answer,
        verdict=verdict,
        question_event=question,
        max_evidence_retries=1,
    )


def test_deterministic_finance_adjudication_accepts_false_rejected_answer():
    question = QuestionEvent(
        example_id="fin-aapl-20250927-0002",
        question=(
            "For the year in which 'Products' net sales reached their minimum among "
            "the three years shown, what was the corresponding 'Gross margin' value, "
            "and is this value also the minimum, typical, or maximum among the three "
            "years' gross margins?"
        ),
        doc_id="aapl-20250927",
        pages_available=1,
        domain="finance",
        answer_type="exact_match",
    )
    evidence = EvidenceEvent(
        packets=[
            _make_packet(packet_id="pkt_000", page=40, bbox=(0.0, 0.0, 1.0, 1.0)).model_copy(
                update={
                    "ocr_snippet": (
                        "Gemini structured extraction: kind=table\n"
                        "headers: Years ended | September 27, 2025 | September 28, 2024 | "
                        "September 30, 2023\n"
                        "candidate_rows: Products | $ 307,003 | $ 294,866 | $ 298,085 | "
                        "Gross margin | 195,201 | 180,683 | 169,148\n"
                        "confidence=0.95"
                    )
                }
            )
        ]
    )
    answer = AnswerEvent(answer="180,683; typical", citations=["pkt_000"], confidence=0.96)
    verdict = VerdictEvent(
        supported=False,
        reason="Verifier selected the wrong year.",
        next_action="escalate_reasoner",
        confidence=0.7,
    )

    adjudicated = _maybe_accept_deterministic_finance_answer(
        question_event=question,
        evidence=evidence,
        answer=answer,
        verdict=verdict,
    )

    assert adjudicated.supported
    assert adjudicated.next_action == "accept"
    assert adjudicated.diagnostics["finance_adjudication"]["mechanism"] == (
        "corresponding_value_status"
    )


def test_deterministic_finance_adjudication_does_not_accept_mismatch():
    question = QuestionEvent(
        example_id="fin-aapl-20250927-0002",
        question=(
            "For the year in which 'Products' net sales reached their minimum among "
            "the three years shown, what was the corresponding 'Gross margin' value, "
            "and is this value also the minimum, typical, or maximum among the three "
            "years' gross margins?"
        ),
        doc_id="aapl-20250927",
        pages_available=1,
        domain="finance",
        answer_type="exact_match",
    )
    evidence = EvidenceEvent(
        packets=[
            _make_packet(packet_id="pkt_000", page=40, bbox=(0.0, 0.0, 1.0, 1.0)).model_copy(
                update={
                    "ocr_snippet": (
                        "headers: Years ended | September 27, 2025 | September 28, 2024 | "
                        "September 30, 2023\n"
                        "candidate_rows: Products | $ 307,003 | $ 294,866 | $ 298,085 | "
                        "Gross margin | 195,201 | 180,683 | 169,148"
                    )
                }
            )
        ]
    )
    answer = AnswerEvent(answer="169,148; minimum", citations=["pkt_000"], confidence=0.99)
    verdict = VerdictEvent(
        supported=False,
        reason="Still unsupported.",
        next_action="escalate_reasoner",
        confidence=0.7,
    )

    assert (
        _maybe_accept_deterministic_finance_answer(
            question_event=question,
            evidence=evidence,
            answer=answer,
            verdict=verdict,
        )
        is verdict
    )


def test_deterministic_finance_adjudication_accepts_purchase_price_percent():
    question = QuestionEvent(
        example_id="fin-segment-percent",
        question=(
            "Using the information from the purchase price allocation and the "
            "segment table showing the impact of acquisitions, determine which "
            "business segment was primarily affected by the acquisition and "
            "calculate what percentage of the total purchase price is represented "
            "by the increase in net assets for that segment. Show your answer as "
            "a percentage to the nearest whole number."
        ),
        doc_id="10-K",
        pages_available=2,
        domain="finance",
        answer_type="numeric",
    )
    evidence = EvidenceEvent(
        packets=[
            _make_packet(packet_id="pkt_000", page=98, bbox=(0.0, 0.0, 1.0, 1.0)).model_copy(
                update={
                    "ocr_snippet": (
                        "headers: (In millions) | June 30, 2023 | Acquisitions | Other | "
                        "June 30, 2024\n"
                        "candidate_rows: Productivity and Business Processes | $ 31,359 | "
                        "$ 0 | $ 2 | $ 31,361 | Intelligent Cloud | 25,676 | 0 | "
                        "(28) | 25,648 | More Personal Computing | 10,851 | 51,235 | "
                        "125 | 62,211 | Total | $ 67,886 | $ 51,235 | $ 99 | $ 119,220"
                    )
                }
            ),
            _make_packet(packet_id="pkt_001", page=97, bbox=(0.0, 0.0, 1.0, 1.0)).model_copy(
                update={
                    "ocr_snippet": (
                        "headers: (In millions)\n"
                        "candidate_rows: Goodwill | 51,001 | Intangible assets | 21,969 | "
                        "Total purchase price | $ 75,408\n"
                        "notes: Goodwill was assigned to our More Personal Computing segment."
                    )
                }
            ),
        ]
    )
    answer = AnswerEvent(answer="68%", citations=["pkt_000", "pkt_001"], confidence=0.87)
    verdict = VerdictEvent(
        supported=False,
        reason="Verifier agrees with the facts but asks for another reasoner pass.",
        next_action="escalate_reasoner",
        confidence=0.72,
    )

    adjudicated = _maybe_accept_deterministic_finance_answer(
        question_event=question,
        evidence=evidence,
        answer=answer,
        verdict=verdict,
    )

    assert adjudicated.supported
    assert adjudicated.next_action == "accept"
    assert adjudicated.diagnostics["finance_adjudication"]["mechanism"] == (
        "segment_purchase_price_percent"
    )


# ---------------------------------------------------------------------------
# FocusWorkflow.run end-to-end (requires parser-bench submodule)
# ---------------------------------------------------------------------------


class _FakeClient:
    """Minimal ModelClient recording the prompts/images it sees."""

    def __init__(self, response_text: str, tokens_in: int = 150, tokens_out: int = 30) -> None:
        self._text = response_text
        self._tokens_in = tokens_in
        self._tokens_out = tokens_out
        self.calls: list[dict[str, Any]] = []

    async def predict(
        self,
        prompt: str,
        images: list[Path] | None = None,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        self.calls.append({"prompt": prompt, "n_images": len(images or []), "system": system})
        return ModelResponse(
            text=self._text,
            tokens_in=self._tokens_in,
            tokens_out=self._tokens_out,
            usd=0.002,
            latency_ms=80,
        )

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)


def _make_example():
    """Build a minimal BenchmarkExample. Call-site gates on submodule."""
    from focusparse._parser_bench import BBox, BenchmarkExample

    return BenchmarkExample(
        id="ex-1",
        domain="datasheet",
        source_pdf="datasheet-A.pdf",
        page_images=[
            "data/processed/datasheet-A/images/datasheet-A_page_0003_300dpi.png",
            "data/processed/datasheet-A/images/datasheet-A_page_0007_300dpi.png",
        ],
        question="What is the max supply voltage?",
        answer="5.5",
        answer_type="numeric",
        answer_unit="V",
        tolerance=0.01,
        supporting_pages=[3],
        supporting_bboxes=[BBox(page=3, x0=0.1, y0=0.2, x1=0.3, y1=0.4)],
        alternate_bboxes=[],
        evidence_relations=[],
        multi_region_required=False,
        requires_visual=True,
        difficulty={"visual": 2, "reasoning": 1, "localization": 3},
        question_family="min_typ_max_disambiguation",
        stress_type="none",
        reasoning_chain=None,
        evidence_page_spread=0,
        adversarial_type=None,
        split="dev",
        original_bboxes=[],
    )


def _make_packet(*, packet_id: str, page: int, bbox: tuple[float, float, float, float]):
    return EvidencePacket(
        packet_id=packet_id,
        page=page,
        bbox_norm=bbox,
        page_thumbnail_ref=f"/tmp/{packet_id}.png",
        local_crop_ref=f"/tmp/{packet_id}.png",
        provenance=PacketProvenance(tool="test", args_hash=""),
    )


def test_infer_doc_id_uses_source_pdf_stem(parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")
    example = _make_example()
    assert _infer_doc_id(example) == "datasheet-A"


async def test_focus_workflow_runs_end_to_end(tmp_path, parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")

    # Reasoner returns a valid JSON referencing one of the packets the
    # skeleton inspector will produce. Packets are named pkt_000, pkt_001 in
    # page order, matching the skeleton's region_id -> packet_id mapping.
    client = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.8}')
    workflow = FocusWorkflow(backend_client=client)
    example = _make_example()

    # Skeleton inspector reads the image path but doesn't open the file.
    images = [
        tmp_path / "datasheet-A_page_0003_300dpi.png",
        tmp_path / "datasheet-A_page_0007_300dpi.png",
    ]
    result = await workflow.run(example, images, protocol="focus")

    assert result.answer == "5.5"

    # Citation resolves back to the packet referenced — pkt_000 is the first
    # region, which the skeleton router emits for the lowest real page number
    # parsed from the filenames (page 3).
    assert len(result.citations) == 1
    assert result.citations[0]["page"] == 3
    assert result.citations[0]["bbox"] == [0.0, 0.0, 1.0, 1.0]

    # Eight recorded steps, one per @step. `rerank` was added in item 4
    # (Phase 2 SOTA-leverage tail) between `localize` and `inspect`; it
    # short-circuits to "skeleton" tier when no `localizer_rerank` client
    # is wired (the case here — no tier_router).
    stages = [step.stage for step in result.trace.steps]
    assert stages == [
        "plan",
        "route_pages",
        "localize",
        "rerank",
        "inspect",
        "expand_context",
        "answer",
        "verify",
    ]

    # Exactly one LLM call — the reasoner.
    llm_steps = [s for s in result.trace.steps if s.action == "llm_call"]
    assert len(llm_steps) == 1
    assert llm_steps[0].stage == "answer"
    assert llm_steps[0].tokens_in == 150
    assert llm_steps[0].tokens_out == 30
    assert llm_steps[0].usd == 0.002

    # Backend was called once with the reasoner prompt + all packet images.
    assert len(client.calls) == 1
    # Two images were passed in -> skeleton yields one packet per page -> two
    # unique local_crop_refs -> reasoner sees both.
    assert client.calls[0]["n_images"] == 2
    assert "pkt_0" in client.calls[0]["prompt"]  # packet ids enumerated

    # Telemetry propagates from the reasoner response.
    assert result.telemetry["tokens_in"] == 150
    assert result.telemetry["tokens_out"] == 30

    # Schema v3 debug trail: page candidates, regions, evidence, answer,
    # and verdict are visible to the one-example dashboard.
    event_types = {(e.stage, e.event_type) for e in result.trace.debug_events}
    assert ("route_pages", "candidate_pages") in event_types
    assert ("localize", "candidate_regions") in event_types
    assert ("inspect", "evidence_packets") in event_types
    assert ("answer", "answer") in event_types
    assert ("verify", "verdict") in event_types
    artifact_kinds = {a.kind for a in result.trace.artifacts}
    assert "page_image" in artifact_kinds
    assert "crop" in artifact_kinds


async def test_focus_workflow_drops_invalid_citation_refs(tmp_path, parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")

    # Reasoner hallucinates packet ids that don't exist → should be silently
    # dropped, leaving only the valid one.
    client = _FakeClient(
        '{"answer": "5.5", "citations": ["pkt_000", "pkt_999", "pkt_001"], "confidence": 0.7}'
    )
    workflow = FocusWorkflow(backend_client=client)
    example = _make_example()
    images = [
        tmp_path / "datasheet-A_page_0003_300dpi.png",
        tmp_path / "datasheet-A_page_0007_300dpi.png",
    ]
    result = await workflow.run(example, images, protocol="focus")

    # Reasoner returned pkt_000, pkt_999 (hallucination), pkt_001. Valid
    # packet set filters to {pkt_000, pkt_001} — pkt_999 is dropped.
    assert len(result.citations) == 2


async def test_focus_workflow_handles_non_json_reasoner_response(
    tmp_path, parser_bench_submodule_present
):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")

    client = _FakeClient("I think it's 5.5 volts but I'm not sure.")
    workflow = FocusWorkflow(backend_client=client)
    example = _make_example()
    images = [tmp_path / "datasheet-A_page_0003_300dpi.png"]
    result = await workflow.run(example, images, protocol="focus")

    # Non-JSON reasoner text falls back to raw text, zero citations.
    assert "5.5" in result.answer
    assert result.citations == []
    # But the workflow still records all 7 steps.
    assert len(result.trace.steps) == 8  # 7 stages + rerank (item 4)


async def test_focus_workflow_survives_zero_pages(tmp_path, parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")

    client = _FakeClient('{"answer": "Unanswerable", "citations": [], "confidence": 0.1}')
    workflow = FocusWorkflow(backend_client=client)
    example = _make_example()
    # No images → zero packets → reasoner still called but with no attachments.
    result = await workflow.run(example, [], protocol="focus")

    assert result.answer == "Unanswerable"
    assert result.citations == []
    # Still 7 steps.
    assert len(result.trace.steps) == 8  # 7 stages + rerank (item 4)
    # Reasoner got called with zero images (packet list empty).
    assert len(client.calls) == 1
    assert client.calls[0]["n_images"] == 0


class _FakeTierRouter:
    """Routes role-scoped clients from a supplied dict. Any role not in the
    dict returns None (the workflow treats None as "deterministic fallback"
    for that stage)."""

    def __init__(self, clients: dict[str, Any] | None = None, **kwargs):
        # Allow either `_FakeTierRouter({"planner": c})` or
        # `_FakeTierRouter(planner=c, verifier=c2)`.
        merged: dict[str, Any] = dict(clients or {})
        merged.update(kwargs)
        self._clients = merged
        self.calls: list[str] = []

    def client_for(self, role: str, *, escalate: bool = False):
        self.calls.append(role)
        return self._clients.get(role)


async def test_focus_workflow_routes_planner_through_tier_router(
    tmp_path, parser_bench_submodule_present
):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")

    # Planner returns a valid datasheet-family classification; reasoner then
    # emits a normal packet-citation answer.
    planner_client = _FakeClient(
        '{"question_family": "min_typ_max_disambiguation", '
        '"evidence_types": ["table", "footnote"], '
        '"budget_class": "easy_local", '
        '"routing_policy": "text_first"}',
        tokens_in=90,
        tokens_out=20,
    )
    reasoner_client = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.9}')
    tier_router = _FakeTierRouter(planner=planner_client)
    workflow = FocusWorkflow(backend_client=reasoner_client, tier_router=tier_router)
    example = _make_example()
    images = [
        tmp_path / "datasheet-A_page_0003_300dpi.png",
        tmp_path / "datasheet-A_page_0007_300dpi.png",
    ]
    result = await workflow.run(example, images, protocol="focus")

    # Router was consulted for every role-scoped stage:
    #   - planner (item 1)
    #   - localizer_rerank (item 4 rerank stage)
    #   - schema_extractor (Gemini table/chart extraction role)
    #   - localizer_rerank fallback when the fake router has no schema client
    #   - verifier
    # Verifier client + rerank client both return None here → those stages
    # stay deterministic; only the planner routes through to a real client.
    assert tier_router.calls == [
        "planner",
        "localizer_rerank",
        "schema_extractor",
        "localizer_rerank",
        "verifier",
    ]
    assert len(planner_client.calls) == 1
    plan_steps = [s for s in result.trace.steps if s.stage == "plan"]
    assert len(plan_steps) == 1
    assert plan_steps[0].action == "llm_call"
    assert plan_steps[0].tier == "cheap"
    assert plan_steps[0].tokens_in == 90
    assert plan_steps[0].tokens_out == 20
    assert plan_steps[0].args["question_family"] == "min_typ_max_disambiguation"
    assert plan_steps[0].args["routing_policy"] == "text_first"
    # Reasoner still answered correctly downstream.
    assert result.answer == "5.5"
    assert len(result.citations) == 1


async def test_focus_workflow_routes_verifier_through_tier_router(
    tmp_path, parser_bench_submodule_present
):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")

    reasoner_client = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.9}')
    verifier_client = _FakeClient(
        '{"supported": false, "reason": "cited bbox covers the wrong row", '
        '"next_action": "retry_localization", "confidence": 0.72}',
        tokens_in=140,
        tokens_out=35,
    )
    tier_router = _FakeTierRouter(verifier=verifier_client)
    # `max_retries=0` keeps this test focused on tier-router wiring, not
    # the verifier→retry loop. The loop's behavior is covered by the
    # dedicated retry-loop tests below.
    workflow = FocusWorkflow(backend_client=reasoner_client, tier_router=tier_router, max_retries=0)
    example = _make_example()
    images = [tmp_path / "datasheet-A_page_0003_300dpi.png"]
    result = await workflow.run(example, images, protocol="focus")

    # Verifier was called once through the tier router, and the verify step
    # records its telemetry.
    assert "verifier" in tier_router.calls
    assert len(verifier_client.calls) == 1
    verify_steps = [s for s in result.trace.steps if s.stage == "verify"]
    assert len(verify_steps) == 1
    step = verify_steps[0]
    assert step.action == "llm_call"
    assert step.tier == "mid"
    assert step.tokens_in == 140
    assert step.tokens_out == 35
    assert step.args["next_action"] == "retry_localization"
    assert step.args["supported"] is False
    # Workflow still terminates after one pass — the retry loop lands later.
    assert result.answer == "5.5"


async def test_focus_workflow_plan_step_deterministic_when_no_tier_router(
    tmp_path, parser_bench_submodule_present
):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")

    client = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.7}')
    workflow = FocusWorkflow(backend_client=client)  # no tier_router
    example = _make_example()
    images = [tmp_path / "datasheet-A_page_0003_300dpi.png"]
    result = await workflow.run(example, images, protocol="focus")

    # No tier_router → planner falls back to deterministic; action reflects that.
    plan_steps = [s for s in result.trace.steps if s.stage == "plan"]
    assert plan_steps[0].action == "deterministic"
    assert plan_steps[0].tier == "skeleton"
    assert plan_steps[0].tokens_in == 0
    # Exactly one LLM call total — the reasoner. Planner did not hit the network.
    llm_steps = [s for s in result.trace.steps if s.action == "llm_call"]
    assert len(llm_steps) == 1
    assert llm_steps[0].stage == "answer"


# ---------------------------------------------------------------------------
# PDF text-layer wiring (Phase 3: get_text_layer → router)
# ---------------------------------------------------------------------------


def _write_pdf_for_workflow_test(path: Path, *, pages_text: dict[int, str]) -> Path:
    """Write a multi-page PDF with the supplied per-page text.

    Keys are 1-indexed so callers can mirror the BenchmarkExample's
    `page_images` list.
    """
    import fitz

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    for page_idx in sorted(pages_text):
        page = doc.new_page(width=600, height=800)
        page.insert_text((50, 50), pages_text[page_idx], fontsize=12)
    doc.save(path)
    doc.close()
    return path


async def test_focus_workflow_routes_through_fts_when_pdf_supplied(
    tmp_path, parser_bench_submodule_present
):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")

    # The skeleton example has page_images for pages 3 and 7; build a PDF
    # where pages 1..7 all exist, but only page 3 mentions the query term
    # so FTS picks it and page 7 ends up in the no-match tail.
    pdf_pages = {i: "unrelated filler content" for i in range(1, 8)}
    pdf_pages[3] = "VCC maximum supply voltage rating is 5.5 volts"
    pdf = _write_pdf_for_workflow_test(tmp_path / "datasheet-A.pdf", pages_text=pdf_pages)

    client = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.8}')
    workflow = FocusWorkflow(backend_client=client)
    example = _make_example()

    images = [
        tmp_path / "datasheet-A_page_0003_300dpi.png",
        tmp_path / "datasheet-A_page_0007_300dpi.png",
    ]
    result = await workflow.run(example, images, protocol="focus", pdf_path=pdf)

    route_step = next(s for s in result.trace.steps if s.stage == "route_pages")
    assert route_step.tier == "text_fts"
    # Page 3 has text "VCC ... max ... supply voltage"; page 7 has only
    # filler, so page 3 should appear in the candidates and be ranked first.
    candidates = route_step.args["candidates"]
    assert 3 in candidates
    # n_text_pages counts how many of the page universe had a non-empty
    # native text layer — all 2 here.
    assert route_step.args["n_text_pages"] == 2


async def test_focus_workflow_skeleton_router_when_no_pdf_path(
    tmp_path, parser_bench_submodule_present
):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")

    client = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.7}')
    workflow = FocusWorkflow(backend_client=client)
    example = _make_example()
    images = [tmp_path / "datasheet-A_page_0003_300dpi.png"]

    # No pdf_path → router falls back to the skeleton path.
    result = await workflow.run(example, images, protocol="focus")

    route_step = next(s for s in result.trace.steps if s.stage == "route_pages")
    assert route_step.tier == "skeleton"
    assert route_step.args["n_text_pages"] == 0


async def test_focus_workflow_skeleton_router_when_pdf_missing_on_disk(
    tmp_path, parser_bench_submodule_present
):
    """Dangling pdf_path should degrade to skeleton, not crash the run."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")

    client = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.7}')
    workflow = FocusWorkflow(backend_client=client)
    example = _make_example()
    images = [tmp_path / "datasheet-A_page_0003_300dpi.png"]

    missing_pdf = tmp_path / "not-there.pdf"
    result = await workflow.run(example, images, protocol="focus", pdf_path=missing_pdf)

    route_step = next(s for s in result.trace.steps if s.stage == "route_pages")
    assert route_step.tier == "skeleton"
    # Run still produced an answer — the missing PDF didn't take the pipeline down.
    assert result.answer == "5.5"


async def test_focus_workflow_tolerates_out_of_range_pages_in_pdf(
    tmp_path, parser_bench_submodule_present
):
    """PDF has fewer pages than page_images → out-of-range pages fall back quietly."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")

    # PDF has only 2 pages; example expects page 3 + page 7.
    pdf = _write_pdf_for_workflow_test(
        tmp_path / "short.pdf",
        pages_text={1: "page one", 2: "page two"},
    )

    client = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.7}')
    workflow = FocusWorkflow(backend_client=client)
    example = _make_example()
    images = [
        tmp_path / "datasheet-A_page_0003_300dpi.png",
        tmp_path / "datasheet-A_page_0007_300dpi.png",
    ]
    # Should still complete: pages 3 and 7 get empty-string text entries,
    # which means FTS matches nothing, so the router returns the no-match
    # fallback — the run keeps going.
    result = await workflow.run(example, images, protocol="focus", pdf_path=pdf)
    assert result.answer == "5.5"
    route_step = next(s for s in result.trace.steps if s.stage == "route_pages")
    assert route_step.tier == "text_fts"
    assert route_step.args["n_text_pages"] == 0


# ---------------------------------------------------------------------------
# Verifier→retry loop (Phase 2 item 3)
# ---------------------------------------------------------------------------


class _ScriptedClient:
    """ModelClient that yields a scripted sequence of responses.

    Returns the i-th response on the i-th call. After the script is
    exhausted, repeats the last response (so a forgotten retry doesn't
    surface as an exception — it surfaces as "the verifier kept saying
    the same thing", which is exactly the case the loop's exhaustion
    branch is supposed to handle).
    """

    def __init__(
        self,
        responses: list[str],
        *,
        tokens_in: int = 100,
        tokens_out: int = 25,
    ) -> None:
        self._responses = list(responses)
        self._tokens_in = tokens_in
        self._tokens_out = tokens_out
        self.calls: list[dict[str, Any]] = []

    async def predict(
        self,
        prompt: str,
        images: list[Path] | None = None,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        idx = min(len(self.calls), len(self._responses) - 1)
        self.calls.append({"prompt": prompt, "n_images": len(images or []), "system": system})
        return ModelResponse(
            text=self._responses[idx],
            tokens_in=self._tokens_in,
            tokens_out=self._tokens_out,
            usd=0.001,
            latency_ms=40,
        )

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)


def _verdict_json(
    *,
    supported: bool,
    next_action: str,
    reason: str = "test reason",
    confidence: float = 0.7,
) -> str:
    return (
        f'{{"supported": {str(supported).lower()}, '
        f'"next_action": "{next_action}", '
        f'"reason": "{reason}", '
        f'"confidence": {confidence}}}'
    )


async def test_loop_accept_on_first_verdict_no_retries(tmp_path, parser_bench_submodule_present):
    """Verifier says accept on first call → no retries, telemetry shows
    loop_terminated=accepted, retries_used=0, retry_helped=None."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    reasoner = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.9}')
    verifier = _FakeClient(_verdict_json(supported=True, next_action="accept"))
    tier_router = _FakeTierRouter(verifier=verifier)
    workflow = FocusWorkflow(backend_client=reasoner, tier_router=tier_router)

    result = await workflow.run(
        _make_example(), [tmp_path / "datasheet-A_page_0003_300dpi.png"], protocol="focus"
    )
    assert result.telemetry["retries_used"] == 0
    assert result.telemetry["loop_terminated"] == "accepted"
    assert result.telemetry["loop_retry_helped"] is None
    # Answer + verify each ran once.
    answer_steps = [s for s in result.trace.steps if s.stage == "answer"]
    verify_steps = [s for s in result.trace.steps if s.stage == "verify"]
    assert len(answer_steps) == 1
    assert len(verify_steps) == 1


async def test_loop_retry_localization_reruns_localize_inspect_expand_answer_verify(
    tmp_path, parser_bench_submodule_present
):
    """retry_localization fires once → localize/inspect/expand/answer/verify each
    run twice (initial + 1 retry). Verifier accepts on the second pass."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    reasoner = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.9}')
    verifier = _ScriptedClient(
        [
            _verdict_json(supported=False, next_action="retry_localization"),
            _verdict_json(supported=True, next_action="accept"),
        ]
    )
    # Default `max_retries=0` since the n=30 A/B; pin =2 here to exercise
    # the loop path this test covers.
    workflow = FocusWorkflow(
        backend_client=reasoner,
        tier_router=_FakeTierRouter(verifier=verifier),
        max_retries=2,
    )

    result = await workflow.run(
        _make_example(), [tmp_path / "datasheet-A_page_0003_300dpi.png"], protocol="focus"
    )

    assert result.telemetry["retries_used"] == 1
    assert result.telemetry["loop_terminated"] == "accepted"
    # initial unsupported + final supported → loop helped
    assert result.telemetry["loop_retry_helped"] is True

    stage_counts = _stage_counts(result)
    # Initial pass + 1 retry of the 5 stages downstream of route_pages.
    assert stage_counts["localize"] == 2
    assert stage_counts["inspect"] == 2
    assert stage_counts["expand_context"] == 2
    assert stage_counts["answer"] == 2
    assert stage_counts["verify"] == 2
    # Plan + route_pages still run exactly once — they're outside the loop.
    assert stage_counts["plan"] == 1
    assert stage_counts["route_pages"] == 1


async def test_loop_expand_context_reruns_only_expand_answer_verify(
    tmp_path, parser_bench_submodule_present
):
    """expand_context retry doesn't re-run localize or inspect — those are
    upstream of the change and would re-detect the same regions."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    reasoner = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.9}')
    verifier = _ScriptedClient(
        [
            _verdict_json(
                supported=False,
                next_action="expand_context",
                reason="missing footnote context",
            ),
            _verdict_json(supported=True, next_action="accept"),
        ]
    )
    # Default `max_retries=0` since the n=30 A/B; pin =2 here to exercise
    # the loop path this test covers.
    workflow = FocusWorkflow(
        backend_client=reasoner,
        tier_router=_FakeTierRouter(verifier=verifier),
        max_retries=2,
    )
    result = await workflow.run(
        _make_example(), [tmp_path / "datasheet-A_page_0003_300dpi.png"], protocol="focus"
    )

    stage_counts = _stage_counts(result)
    assert stage_counts["expand_context"] == 2
    assert stage_counts["answer"] == 2
    assert stage_counts["verify"] == 2
    # Localize + inspect stay at 1 — no re-detection.
    assert stage_counts["localize"] == 1
    assert stage_counts["inspect"] == 1

    # The retry expand step records a wider adjacency_pad in args.
    expand_steps = [s for s in result.trace.steps if s.stage == "expand_context"]
    pads = [s.args.get("adjacency_pad") for s in expand_steps]
    assert pads[0] < pads[1], f"adjacency_pad should grow on retry; got {pads}"
    assert expand_steps[1].args["verifier_missing_context"] == ["footnote"]
    assert expand_steps[1].args["verifier_reason"] == "missing footnote context"
    assert expand_steps[1].args["target_packet_ids"] == ["pkt_000"]
    assert "n_neighbors_added" in expand_steps[1].args
    answer_steps = [s for s in result.trace.steps if s.stage == "answer"]
    assert answer_steps[0].args.get("had_escalation_hint") is False
    assert answer_steps[1].args.get("had_escalation_hint") is True


async def test_loop_expand_context_retries_once_by_default(
    tmp_path, parser_bench_submodule_present
):
    """Evidence-only retries have one default budget even when localization
    retries are disabled. This lets verifier feedback repair inspect/expand
    evidence without re-opening the noisy localization retry path."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    reasoner = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.9}')
    verifier = _ScriptedClient(
        [
            _verdict_json(supported=False, next_action="expand_context"),
            _verdict_json(supported=True, next_action="accept"),
        ]
    )
    workflow = FocusWorkflow(
        backend_client=reasoner,
        tier_router=_FakeTierRouter(verifier=verifier),
    )

    result = await workflow.run(
        _make_example(), [tmp_path / "datasheet-A_page_0003_300dpi.png"], protocol="focus"
    )

    assert result.telemetry["retries_used"] == 1
    assert result.telemetry["evidence_retries_used"] == 1
    assert result.telemetry["loop_terminated"] == "accepted"
    stage_counts = _stage_counts(result)
    assert stage_counts["localize"] == 1
    assert stage_counts["inspect"] == 1
    assert stage_counts["expand_context"] == 2
    assert stage_counts["answer"] == 2
    assert stage_counts["verify"] == 2


async def test_loop_expand_context_records_tool_retry_answer_change(
    tmp_path, parser_bench_submodule_present
):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")

    reasoner = _ScriptedClient(
        [
            '{"answer": "about 50%", "citations": ["pkt_000"], "confidence": 0.5}',
            '{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.9}',
        ]
    )
    verifier = _ScriptedClient(
        [
            _verdict_json(supported=False, next_action="expand_context"),
            _verdict_json(supported=True, next_action="accept"),
        ]
    )
    workflow = FocusWorkflow(
        backend_client=reasoner,
        tier_router=_FakeTierRouter(verifier=verifier),
    )

    result = await workflow.run(
        _make_example(), [tmp_path / "datasheet-A_page_0003_300dpi.png"], protocol="focus"
    )

    assert result.telemetry["answer_changed_after_tool"] is True
    assert result.telemetry["verifier_supported_after_tool"] is True


async def test_loop_expand_context_visual_readability_retry_zooms_target_crop(
    tmp_path, monkeypatch, parser_bench_submodule_present
):
    """Unreadable visual evidence gets a zoom retry, not broader neighbors."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")

    async def _fake_zoom_crop(*, crop_ref, cache_dir, packet_id):
        return str(tmp_path / f"{packet_id}_zoomed.png")

    monkeypatch.setattr("focusparse.pipeline.expander._zoom_crop", _fake_zoom_crop)
    reasoner = _ScriptedClient(
        [
            '{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.4}',
            '{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.9}',
        ]
    )
    verifier = _ScriptedClient(
        [
            _verdict_json(
                supported=False,
                next_action="expand_context",
                reason="pkt_000 crop is blurry and the axis label is unreadable",
            ),
            _verdict_json(supported=True, next_action="accept"),
        ]
    )
    workflow = FocusWorkflow(
        backend_client=reasoner,
        tier_router=_FakeTierRouter(verifier=verifier),
    )

    result = await workflow.run(
        _make_example(), [tmp_path / "datasheet-A_page_0003_300dpi.png"], protocol="focus"
    )

    expand_steps = [s for s in result.trace.steps if s.stage == "expand_context"]
    assert expand_steps[1].args["visual_readability_retry"] is True
    assert expand_steps[1].args["n_zoomed_added"] == 1
    assert expand_steps[1].args["n_neighbors_added"] == 0
    assert reasoner.calls[1]["n_images"] > reasoner.calls[0]["n_images"]


async def test_loop_expand_context_retry_answers_with_target_packets_only(
    tmp_path, parser_bench_submodule_present
):
    """Verifier-targeted evidence retries do not resend every packet."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    reasoner = _ScriptedClient(
        [
            '{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.4}',
            '{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.9}',
        ]
    )
    verifier = _ScriptedClient(
        [
            _verdict_json(
                supported=False,
                next_action="expand_context",
                reason="pkt_000 needs clearer supporting context",
            ),
            _verdict_json(supported=True, next_action="accept"),
        ]
    )
    workflow = FocusWorkflow(
        backend_client=reasoner,
        tier_router=_FakeTierRouter(verifier=verifier),
    )

    result = await workflow.run(
        _make_example(),
        [
            tmp_path / "datasheet-A_page_0003_300dpi.png",
            tmp_path / "datasheet-A_page_0007_300dpi.png",
        ],
        protocol="focus",
    )

    answer_steps = [s for s in result.trace.steps if s.stage == "answer"]
    assert answer_steps[0].args["n_packets"] == 2
    assert answer_steps[0].args["evidence_scope"] == "full"
    assert answer_steps[1].args["n_packets"] == 1
    assert answer_steps[1].args["evidence_scope"] == "targeted"
    assert "pkt_000" in reasoner.calls[1]["prompt"]
    assert "pkt_001" not in reasoner.calls[1]["prompt"]


async def test_loop_exhausted_keeps_best_unsupported_answer(
    tmp_path, parser_bench_submodule_present
):
    """If an evidence retry remains unsupported, do not let it overwrite a
    higher-confidence prior answer.

    This pins the timing-diagram failure where the first answer was `4 µs`,
    the verifier requested more context, and the retry drifted to `8 µs`.
    """
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    reasoner = _ScriptedClient(
        [
            '{"answer": "4 µs", "citations": ["pkt_000"], "confidence": 0.74}',
            '{"answer": "8 µs", "citations": ["pkt_000"], "confidence": 0.64}',
        ]
    )
    verifier = _ScriptedClient(
        [
            _verdict_json(supported=False, next_action="expand_context"),
            _verdict_json(supported=False, next_action="expand_context"),
        ]
    )
    workflow = FocusWorkflow(
        backend_client=reasoner,
        tier_router=_FakeTierRouter(verifier=verifier),
    )

    result = await workflow.run(
        _make_example(), [tmp_path / "datasheet-A_page_0003_300dpi.png"], protocol="focus"
    )

    assert result.answer == "4 µs"
    assert result.telemetry["retries_used"] == 1
    assert result.telemetry["loop_terminated"] == "exhausted"
    selection_events = [
        e for e in result.trace.debug_events if e.stage == "answer" and e.event_type == "selection"
    ]
    assert selection_events
    assert selection_events[-1].payload["selected"] == "best_unsupported"


async def test_retry_abstain_keeps_cited_unsupported_answer(
    tmp_path, parser_bench_submodule_present
):
    """A late abstain after evidence repair should not erase a cited answer.

    This pins the ADS1299 regression where the first answer was the scorer-
    correct `10 mA`, the verifier requested more context, and the post-retry
    verdict abstained even though the best answer still had citations.
    """
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    reasoner = _ScriptedClient(
        [
            '{"answer": "10 mA", "citations": ["pkt_000"], "confidence": 0.91}',
            '{"answer": "10 mA", "citations": ["pkt_000"], "confidence": 0.42}',
        ]
    )
    verifier = _ScriptedClient(
        [
            _verdict_json(supported=False, next_action="expand_context"),
            _verdict_json(supported=False, next_action="abstain"),
        ]
    )
    workflow = FocusWorkflow(
        backend_client=reasoner,
        tier_router=_FakeTierRouter(verifier=verifier),
    )

    result = await workflow.run(
        _make_example(), [tmp_path / "datasheet-A_page_0003_300dpi.png"], protocol="focus"
    )

    assert result.answer == "10 mA"
    assert result.citations
    assert result.telemetry["loop_terminated"] == "exhausted"
    selection_events = [
        e for e in result.trace.debug_events if e.stage == "answer" and e.event_type == "selection"
    ]
    assert selection_events[-1].payload["reason"] == "retry_abstain_after_evidence_repair"


async def test_loop_expand_context_with_no_citations_targets_no_packets(
    tmp_path, parser_bench_submodule_present
):
    """Verifier-directed expansion needs a packet anchor; empty citations
    become a focused reasoner retry instead of expanding all packets."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    reasoner = _ScriptedClient(
        [
            '{"answer": "5.5", "citations": [], "confidence": 0.4}',
            '{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.9}',
        ]
    )
    verifier = _ScriptedClient(
        [
            _verdict_json(
                supported=False,
                next_action="expand_context",
                reason="missing caption context",
            ),
            _verdict_json(supported=True, next_action="accept"),
        ]
    )
    workflow = FocusWorkflow(
        backend_client=reasoner,
        tier_router=_FakeTierRouter(verifier=verifier),
    )

    result = await workflow.run(
        _make_example(), [tmp_path / "datasheet-A_page_0003_300dpi.png"], protocol="focus"
    )

    expand_steps = [s for s in result.trace.steps if s.stage == "expand_context"]
    assert expand_steps[1].args["target_packet_ids"] == []
    assert expand_steps[1].args["n_neighbors_added"] == 0
    answer_steps = [s for s in result.trace.steps if s.stage == "answer"]
    assert answer_steps[1].args.get("had_escalation_hint") is True
    assert "missing caption context" in reasoner.calls[1]["prompt"]
    assert "Keep the answer field concise" in reasoner.calls[1]["prompt"]


async def test_loop_evidence_retry_can_be_explicitly_disabled(
    tmp_path, parser_bench_submodule_present
):
    """max_evidence_retries=0 preserves a strict pre-loop baseline for
    evaluator A/Bs that need no controller actions at all."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    reasoner = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.9}')
    verifier = _FakeClient(_verdict_json(supported=False, next_action="expand_context"))
    workflow = FocusWorkflow(
        backend_client=reasoner,
        tier_router=_FakeTierRouter(verifier=verifier),
        max_retries=0,
        max_evidence_retries=0,
    )

    result = await workflow.run(
        _make_example(), [tmp_path / "datasheet-A_page_0003_300dpi.png"], protocol="focus"
    )

    assert result.telemetry["retries_used"] == 0
    assert result.telemetry["evidence_retries_used"] == 0
    assert result.telemetry["loop_terminated"] == "exhausted"
    stage_counts = _stage_counts(result)
    assert stage_counts["expand_context"] == 1
    assert stage_counts["answer"] == 1
    assert stage_counts["verify"] == 1


async def test_loop_escalate_reasoner_reruns_only_answer_verify(
    tmp_path, parser_bench_submodule_present
):
    """escalate_reasoner re-runs only answer + verify. The retry answer call
    carries the verifier's reason as an `escalation_hint`."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    reasoner = _ScriptedClient(
        [
            '{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.4}',
            '{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.9}',
        ]
    )
    verifier = _ScriptedClient(
        [
            _verdict_json(
                supported=False,
                next_action="escalate_reasoner",
                reason="reasoner mis-read the cited table cell",
            ),
            _verdict_json(supported=True, next_action="accept"),
        ]
    )
    # Default `max_retries=0` since the n=30 A/B; pin =2 here to exercise
    # the loop path this test covers.
    workflow = FocusWorkflow(
        backend_client=reasoner,
        tier_router=_FakeTierRouter(verifier=verifier),
        max_retries=2,
    )
    result = await workflow.run(
        _make_example(), [tmp_path / "datasheet-A_page_0003_300dpi.png"], protocol="focus"
    )

    stage_counts = _stage_counts(result)
    assert stage_counts["answer"] == 2
    assert stage_counts["verify"] == 2
    # Localize / inspect / expand all stay at 1 — escalation doesn't touch them.
    assert stage_counts["localize"] == 1
    assert stage_counts["inspect"] == 1
    assert stage_counts["expand_context"] == 1

    # Retry answer step records the escalation hint.
    answer_steps = [s for s in result.trace.steps if s.stage == "answer"]
    assert answer_steps[0].args.get("had_escalation_hint") is False
    assert answer_steps[1].args.get("had_escalation_hint") is True


async def test_loop_escalate_reasoner_is_not_default_evidence_retry(
    tmp_path, parser_bench_submodule_present
):
    """Default evidence retries are reserved for evidence-changing actions.

    `escalate_reasoner` remains available when max_retries is explicitly
    enabled, but the default +4 headline path should not spend another
    frontier answer call without changing inspect/expand packets.
    """
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    reasoner = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.4}')
    verifier = _FakeClient(
        _verdict_json(
            supported=False,
            next_action="escalate_reasoner",
            reason="reasoner mis-read the cited table cell",
        )
    )
    workflow = FocusWorkflow(
        backend_client=reasoner,
        tier_router=_FakeTierRouter(verifier=verifier),
    )

    result = await workflow.run(
        _make_example(), [tmp_path / "datasheet-A_page_0003_300dpi.png"], protocol="focus"
    )

    assert result.telemetry["retries_used"] == 0
    assert result.telemetry["evidence_retries_used"] == 0
    assert result.telemetry["loop_terminated"] == "exhausted"
    stage_counts = _stage_counts(result)
    assert stage_counts["answer"] == 1
    assert stage_counts["verify"] == 1
    assert stage_counts["expand_context"] == 1


async def test_loop_allows_verbose_numeric_shape_retry(tmp_path, parser_bench_submodule_present):
    """Verifier-rejected explanatory numeric prose gets one hinted retry by default."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    reasoner = _ScriptedClient(
        [
            (
                '{"answer": "You might incorrectly report 10%, but the table '
                'shows the requested percentage should be 0%.", '
                '"citations": ["pkt_000"], "confidence": 0.72}'
            ),
            '{"answer": "0%", "citations": ["pkt_000"], "confidence": 0.86}',
        ]
    )
    verifier = _ScriptedClient(
        [
            _verdict_json(
                supported=False,
                next_action="escalate_reasoner",
                reason="The answer is too verbose and does not directly provide the scalar value.",
            ),
            _verdict_json(supported=True, next_action="accept"),
        ]
    )
    workflow = FocusWorkflow(
        backend_client=reasoner,
        tier_router=_FakeTierRouter(verifier=verifier),
    )
    example = _make_example().model_copy(
        update={
            "question": "What percentage should be reported?",
            "answer_type": "numeric",
        }
    )

    result = await workflow.run(
        example, [tmp_path / "datasheet-A_page_0003_300dpi.png"], protocol="focus"
    )

    assert result.answer == "0%"
    assert result.telemetry["retries_used"] == 1
    assert result.telemetry["evidence_retries_used"] == 0
    stage_counts = _stage_counts(result)
    assert stage_counts["answer"] == 2
    assert stage_counts["verify"] == 2
    assert stage_counts["expand_context"] == 1
    assert "Keep the answer field concise" in reasoner.calls[1]["prompt"]


async def test_loop_allows_contract_guard_retry(tmp_path, parser_bench_submodule_present):
    """A verifier false-accept overridden by the contract gets one retry."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    reasoner = _ScriptedClient(
        [
            '{"answer": "0.697", "citations": ["pkt_000"], "confidence": 0.9}',
            '{"answer": "min: 0.697 V", "citations": ["pkt_000"], "confidence": 0.86}',
        ]
    )
    verifier = _ScriptedClient(
        [
            _verdict_json(
                supported=True,
                next_action="accept",
                reason="The value appears in the cited table row.",
            ),
            _verdict_json(supported=True, next_action="accept"),
        ]
    )
    workflow = FocusWorkflow(
        backend_client=reasoner,
        tier_router=_FakeTierRouter(verifier=verifier),
    )
    example = _make_example().model_copy(
        update={
            "question": (
                "Which value (min, typ, or max) should be used, and what is "
                "the corresponding voltage?"
            ),
            "answer_type": "exact_match",
            "question_family": "spec_table_cell_retrieval",
        }
    )

    result = await workflow.run(
        example, [tmp_path / "datasheet-A_page_0003_300dpi.png"], protocol="focus"
    )

    assert result.answer == "min: 0.697 V"
    assert result.telemetry["retries_used"] == 1
    assert result.telemetry["evidence_retries_used"] == 0
    stage_counts = _stage_counts(result)
    assert stage_counts["answer"] == 2
    assert stage_counts["verify"] == 2
    assert "Question answer contract" in reasoner.calls[1]["prompt"]
    assert "Previous answer: 0.697" in reasoner.calls[1]["prompt"]
    assert "Targeted multi-field repair" in reasoner.calls[1]["prompt"]
    assert "Adjudicate candidates internally" in reasoner.calls[1]["prompt"]
    assert "Same-evidence repair worksheet" in reasoner.calls[1]["prompt"]
    assert (
        "Candidate B = same answer completed with all requested fields"
        in reasoner.calls[1]["prompt"]
    )


async def test_loop_allows_single_entity_shape_retry(tmp_path, parser_bench_submodule_present):
    """A list-like answer to a singular entity question gets one hinted retry."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    reasoner = _ScriptedClient(
        [
            '{"answer": "UK and US", "citations": ["pkt_000"], "confidence": 0.89}',
            '{"answer": "Germany", "citations": ["pkt_000"], "confidence": 0.75}',
        ]
    )
    verifier = _ScriptedClient(
        [
            _verdict_json(
                supported=False,
                next_action="escalate_reasoner",
                reason="The answer identifies two countries but the question asks for a single country.",
            ),
            _verdict_json(
                supported=False,
                next_action="expand_context",
                reason="The answer is plausible but still unsupported.",
            ),
        ]
    )
    workflow = FocusWorkflow(
        backend_client=reasoner,
        tier_router=_FakeTierRouter(verifier=verifier),
    )
    example = _make_example().model_copy(
        update={
            "question": "Which country's 10-year government bond yield changed least?",
            "answer_type": "exact_match",
        }
    )

    result = await workflow.run(
        example, [tmp_path / "datasheet-A_page_0003_300dpi.png"], protocol="focus"
    )

    assert result.answer == "Germany"
    assert result.telemetry["retries_used"] == 1
    assert result.telemetry["evidence_retries_used"] == 0
    answer_steps = [s for s in result.trace.steps if s.stage == "answer"]
    assert len(answer_steps) == 2
    assert "Keep the answer field concise" in reasoner.calls[1]["prompt"]


async def test_phase3d_proactive_non_abstain_retry_recovers_lazy_answer(
    tmp_path, parser_bench_submodule_present
):
    """Phase 3d (2026-05-13 sprint): when the initial answer is 'Unanswerable'
    but the reasoner cited at least one evidence packet (i.e. evidence is
    present and the reasoner gave up on extraction), a single proactive
    retry with a 'do not abstain' hint fires before the verifier sees the
    abstention. If the retry produces a concrete answer, it replaces the
    abstention."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    reasoner = _ScriptedClient(
        [
            # Initial: lazy abstain with 1 citation (citations get filtered to
            # the set of actual packet ids; test setup yields packet pkt_000).
            '{"answer": "Unanswerable", "citations": ["pkt_000"], "confidence": 0.3}',
            # Proactive retry: concrete answer
            '{"answer": "0x3FFFF8", "citations": ["pkt_000"], "confidence": 0.9}',
        ]
    )
    verifier = _FakeClient(_verdict_json(supported=True, next_action="accept"))
    workflow = FocusWorkflow(
        backend_client=reasoner,
        tier_router=_FakeTierRouter(verifier=verifier),
        proactive_non_abstain_retry=True,
    )

    result = await workflow.run(
        _make_example(), [tmp_path / "datasheet-A_page_0003_300dpi.png"], protocol="focus"
    )

    assert result.answer == "0x3FFFF8"
    # citations are page/bbox dicts, not packet_id strings
    assert len(result.citations) >= 1
    # The proactive retry produced a debug selection event with the right reason.
    selection_events = [
        e for e in result.trace.debug_events if e.stage == "answer" and e.event_type == "selection"
    ]
    assert any(s.payload.get("selected") == "proactive_non_abstain_retry" for s in selection_events)
    # Verify both reasoner calls happened: initial (no hint) + proactive retry (with hint).
    assert len(reasoner.calls) == 2
    assert "Your previous answer was 'Unanswerable'" in reasoner.calls[1]["prompt"]


async def test_phase3d_skips_retry_when_initial_answer_has_no_citations(
    tmp_path, parser_bench_submodule_present
):
    """Phase 3d guard: when the initial 'Unanswerable' answer cites zero
    packets, the model didn't find candidate evidence so we trust its
    abstention rather than spending a reasoner call on a likely
    hallucinated retry."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    reasoner = _ScriptedClient(
        [
            # Initial: abstain with no citations -> no proactive retry.
            '{"answer": "Unanswerable", "citations": [], "confidence": 0.2}',
        ]
    )
    verifier = _FakeClient(_verdict_json(supported=False, next_action="abstain"))
    workflow = FocusWorkflow(
        backend_client=reasoner,
        tier_router=_FakeTierRouter(verifier=verifier),
        proactive_non_abstain_retry=True,
    )

    result = await workflow.run(
        _make_example(), [tmp_path / "datasheet-A_page_0003_300dpi.png"], protocol="focus"
    )

    # Only one reasoner call was made (no proactive retry).
    assert len(reasoner.calls) == 1
    assert result.answer == "Unanswerable"


async def test_phase3d_flag_off_preserves_legacy_behavior(tmp_path, parser_bench_submodule_present):
    """Phase 3d is gated by `proactive_non_abstain_retry`; passing False
    restores the pre-Phase-3d flow (no proactive retry on lazy abstain)."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    reasoner = _ScriptedClient(
        [
            # Initial: abstain with 2 citations — pre-Phase-3d would NOT retry
            '{"answer": "Unanswerable", "citations": ["pkt_000", "pkt_001"], "confidence": 0.3}',
        ]
    )
    verifier = _FakeClient(_verdict_json(supported=False, next_action="abstain"))
    workflow = FocusWorkflow(
        backend_client=reasoner,
        tier_router=_FakeTierRouter(verifier=verifier),
        proactive_non_abstain_retry=False,
    )

    result = await workflow.run(
        _make_example(), [tmp_path / "datasheet-A_page_0003_300dpi.png"], protocol="focus"
    )

    # Only one reasoner call (flag off — no proactive retry).
    assert len(reasoner.calls) == 1
    assert result.answer == "Unanswerable"


# ---------------------------------------------------------------------------
# Phase 3b (2026-05-14 sprint): reasoner K-sample self-consistency
# ---------------------------------------------------------------------------


async def test_phase3b_k_equals_two_runs_two_reasoner_calls_and_picks_best(
    tmp_path, parser_bench_submodule_present
):
    """Phase 3b: K=2 self-consistency runs both reasoner samples and the
    picker selects the better one (more citations / shorter for
    exact_match). Cost telemetry sums across all K samples."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    reasoner = _ScriptedClient(
        [
            # Sample 0: variant-0 prompt, longer / less-cited answer
            '{"answer": "0x3FFFF8 (the computed translation table base address)", '
            '"citations": ["pkt_000"], "confidence": 0.7}',
            # Sample 1: variant-1 prompt, concise + better-cited answer
            '{"answer": "0x3FFFF8", "citations": ["pkt_000"], "confidence": 0.9}',
        ]
    )
    verifier = _FakeClient(_verdict_json(supported=True, next_action="accept"))
    workflow = FocusWorkflow(
        backend_client=reasoner,
        tier_router=_FakeTierRouter(verifier=verifier),
        reasoner_self_consistency_k=2,
        proactive_non_abstain_retry=False,  # isolate Phase 3b from Phase 3d
    )
    result = await workflow.run(
        _make_example(), [tmp_path / "datasheet-A_page_0003_300dpi.png"], protocol="focus"
    )

    # Both reasoner calls were made (K=2).
    assert len(reasoner.calls) == 2
    # Sample 1 has the verbatim-grounding addendum (variant-1 prompt).
    assert "exact span" in reasoner.calls[1]["prompt"].lower()
    # Sample 0 does not.
    assert "exact span" not in reasoner.calls[0]["prompt"].lower()
    # Picker chose sample 1 (shorter + higher confidence + same citations).
    assert result.answer == "0x3FFFF8"
    assert result.telemetry["tokens_in"] == 200
    assert result.telemetry["tokens_out"] == 50
    assert result.telemetry["usd"] == pytest.approx(0.002)
    sc_events = [
        e
        for e in result.trace.debug_events
        if e.stage == "answer" and e.event_type == "self_consistency"
    ]
    assert sc_events, "expected a self_consistency debug event"
    payload = sc_events[0].payload
    assert payload["k"] == 2
    assert payload["chosen_index"] == 1
    assert payload["all_agree"] is False
    assert len(payload["samples"]) == 2
    answer_step = next(
        s for s in result.trace.steps if s.stage == "answer" and s.action == "llm_call_k"
    )
    assert answer_step.tokens_in == 200
    assert answer_step.tokens_out == 50
    assert answer_step.usd == pytest.approx(0.002)


async def test_phase3b_default_k_one_preserves_legacy_behavior(
    tmp_path, parser_bench_submodule_present
):
    """Phase 3b default is k=1; the workflow falls back to the single-shot
    `answer_from_evidence` path with no self_consistency debug event."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    reasoner = _FakeClient('{"answer": "0x3FFFF8", "citations": ["pkt_000"], "confidence": 0.9}')
    verifier = _FakeClient(_verdict_json(supported=True, next_action="accept"))
    workflow = FocusWorkflow(
        backend_client=reasoner,
        tier_router=_FakeTierRouter(verifier=verifier),
        # reasoner_self_consistency_k defaults to 1
    )
    result = await workflow.run(
        _make_example(), [tmp_path / "datasheet-A_page_0003_300dpi.png"], protocol="focus"
    )

    # Single reasoner call; no Phase 3b debug event.
    assert len(reasoner.calls) == 1
    sc_events = [
        e
        for e in result.trace.debug_events
        if e.stage == "answer" and e.event_type == "self_consistency"
    ]
    assert sc_events == []


async def test_phase3b_invalid_k_raises_value_error() -> None:
    """K must be >= 1; 0 / negative is a config error."""
    import pytest as _pytest

    with _pytest.raises(ValueError):
        FocusWorkflow(
            backend_client=_FakeClient('{"answer": "x", "citations": [], "confidence": 0.5}'),
            reasoner_self_consistency_k=0,
        )


async def test_phase3b_skips_self_consistency_on_retry_calls(
    tmp_path, parser_bench_submodule_present
):
    """Phase 3b runs K samples on the INITIAL answer only. Retry-loop
    answer calls (with escalation_hint) stay k=1 — retries already have
    verifier guidance and double-K-ing them would blow the retry budget."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    reasoner = _ScriptedClient(
        [
            # Initial: K=2 samples
            '{"answer": "wrong-A", "citations": ["pkt_000"], "confidence": 0.4}',
            '{"answer": "wrong-B", "citations": ["pkt_000"], "confidence": 0.5}',
            # Retry: k=1 (no extra samples)
            '{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.9}',
        ]
    )
    verifier = _ScriptedClient(
        [
            _verdict_json(
                supported=False,
                next_action="expand_context",
                reason="missing caption context",
            ),
            _verdict_json(supported=True, next_action="accept"),
        ]
    )
    workflow = FocusWorkflow(
        backend_client=reasoner,
        tier_router=_FakeTierRouter(verifier=verifier),
        reasoner_self_consistency_k=2,
        proactive_non_abstain_retry=False,
    )
    await workflow.run(
        _make_example(), [tmp_path / "datasheet-A_page_0003_300dpi.png"], protocol="focus"
    )

    # 2 initial samples + 1 retry call = 3 total reasoner calls.
    assert len(reasoner.calls) == 3


async def test_loop_abstain_terminates_with_unanswerable(tmp_path, parser_bench_submodule_present):
    """abstain replaces the answer with 'Unanswerable' and ends the loop."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    reasoner = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.9}')
    verifier = _FakeClient(
        _verdict_json(
            supported=False,
            next_action="abstain",
            reason="no evidence for the question",
        )
    )
    # Default `max_retries=0` since the n=30 A/B; pin =2 here to exercise
    # the loop path this test covers.
    workflow = FocusWorkflow(
        backend_client=reasoner,
        tier_router=_FakeTierRouter(verifier=verifier),
        max_retries=2,
    )

    result = await workflow.run(
        _make_example(), [tmp_path / "datasheet-A_page_0003_300dpi.png"], protocol="focus"
    )
    assert result.answer == "Unanswerable"
    assert result.telemetry["loop_terminated"] == "abstained"
    # Abstention was decided on the first verdict — no retries fired.
    assert result.telemetry["retries_used"] == 0
    assert result.citations == []  # abstention drops citations


async def test_loop_exhausted_when_max_retries_hit(tmp_path, parser_bench_submodule_present):
    """Verifier keeps saying retry → loop runs max_retries times and exits as
    `exhausted` with the last (still-unsupported) answer."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    reasoner = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.7}')
    # Always retry. Even at max=2 the loop runs 2 retries then exits.
    verifier = _FakeClient(
        _verdict_json(supported=False, next_action="retry_localization", confidence=0.6)
    )
    workflow = FocusWorkflow(
        backend_client=reasoner,
        tier_router=_FakeTierRouter(verifier=verifier),
        max_retries=2,
    )
    result = await workflow.run(
        _make_example(), [tmp_path / "datasheet-A_page_0003_300dpi.png"], protocol="focus"
    )
    assert result.telemetry["retries_used"] == 2
    assert result.telemetry["loop_terminated"] == "exhausted"
    # Initial false + final still false → retry_helped is False (not None).
    assert result.telemetry["loop_retry_helped"] is False
    # Verify ran 1 + 2 = 3 times.
    stage_counts = _stage_counts(result)
    assert stage_counts["verify"] == 3
    assert stage_counts["localize"] == 3  # initial + 2 retries


async def test_loop_max_retries_zero_disables_loop(tmp_path, parser_bench_submodule_present):
    """max_retries=0 → workflow falls back to pre-loop cascade behavior. The
    verifier's next_action is recorded but never acted on."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    reasoner = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.9}')
    verifier = _FakeClient(_verdict_json(supported=False, next_action="retry_localization"))
    workflow = FocusWorkflow(
        backend_client=reasoner,
        tier_router=_FakeTierRouter(verifier=verifier),
        max_retries=0,
    )
    result = await workflow.run(
        _make_example(), [tmp_path / "datasheet-A_page_0003_300dpi.png"], protocol="focus"
    )
    # Loop didn't fire even though next_action != accept.
    assert result.telemetry["retries_used"] == 0
    assert result.telemetry["loop_terminated"] == "exhausted"
    # Each stage still runs exactly once.
    stage_counts = _stage_counts(result)
    for stage in (
        "plan",
        "route_pages",
        "localize",
        "inspect",
        "expand_context",
        "answer",
        "verify",
    ):
        assert stage_counts[stage] == 1, f"stage {stage} ran {stage_counts[stage]} times"


async def test_loop_unknown_action_terminates_as_accepted(tmp_path, parser_bench_submodule_present):
    """A future verifier extension that emits an unrecognized next_action
    should NOT crash the workflow — it should accept the current answer
    rather than thrash."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    reasoner = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.9}')
    # The verifier's pydantic schema only accepts the 5 known actions, so
    # we can't actually feed an unknown action through the LLM path. We
    # simulate this with a hand-built verifier that bypasses the LLM by
    # returning supported=True, next_action="accept" (the canonical
    # "no-op" path). The branch that handles unknown actions in
    # workflow.run is exercised only via type-erased extensions; the
    # test below just confirms the bail-out path doesn't loop infinitely
    # when the verifier emits a quiet accept.
    verifier = _FakeClient(_verdict_json(supported=True, next_action="accept"))
    # Default `max_retries=0` since the n=30 A/B; pin =2 here to exercise
    # the loop path this test covers.
    workflow = FocusWorkflow(
        backend_client=reasoner,
        tier_router=_FakeTierRouter(verifier=verifier),
        max_retries=2,
    )
    result = await workflow.run(
        _make_example(), [tmp_path / "datasheet-A_page_0003_300dpi.png"], protocol="focus"
    )
    assert result.telemetry["loop_terminated"] == "accepted"
    assert result.telemetry["retries_used"] == 0


def _stage_counts(result) -> dict[str, int]:
    counts: dict[str, int] = {}
    for s in result.trace.steps:
        counts[s.stage] = counts.get(s.stage, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Region reranker wiring (Phase 2 item 4)
# ---------------------------------------------------------------------------


async def test_focus_workflow_routes_rerank_through_tier_router(
    tmp_path, parser_bench_submodule_present
):
    """When `localizer_rerank` is wired through the tier_router, the rerank
    step records its tokens + tier, and the LLM is called once between
    localize and inspect."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")

    reasoner = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.9}')
    # Skeleton inspector emits one packet per region (= one per regions
    # candidate). The rerank LLM scores them; the wiring just needs to
    # confirm the call happened.
    rerank_client = _FakeClient(
        '{"regions": [{"region_id": "r0_p3", "relevance": 0.85, "needed_for": "primary"}]}',
        tokens_in=180,
        tokens_out=50,
    )
    tier_router = _FakeTierRouter(localizer_rerank=rerank_client)
    workflow = FocusWorkflow(backend_client=reasoner, tier_router=tier_router)
    images = [tmp_path / "datasheet-A_page_0003_300dpi.png"]

    result = await workflow.run(_make_example(), images, protocol="focus")

    # Tier router was asked for localizer_rerank (and other roles).
    assert "localizer_rerank" in tier_router.calls
    # Rerank client was called exactly once with the structured prompt.
    assert len(rerank_client.calls) == 1
    assert "Question: What is the max supply voltage?" in rerank_client.calls[0]["prompt"]

    # Trajectory has one rerank step in mid-tier mode.
    rerank_steps = [s for s in result.trace.steps if s.stage == "rerank"]
    assert len(rerank_steps) == 1
    step = rerank_steps[0]
    assert step.action == "llm_call"
    assert step.tier == "mid"
    assert step.tokens_in == 180
    assert step.tokens_out == 50


async def test_focus_workflow_rerank_step_is_skeleton_when_no_router(
    tmp_path, parser_bench_submodule_present
):
    """Without a tier_router (or without a localizer_rerank client), the
    rerank step still appears in the trajectory but at tier=skeleton with
    zero tokens — keeps the step shape stable for trace consumers."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")

    client = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.9}')
    workflow = FocusWorkflow(backend_client=client)  # no tier_router
    images = [tmp_path / "datasheet-A_page_0003_300dpi.png"]
    result = await workflow.run(_make_example(), images, protocol="focus")

    rerank_steps = [s for s in result.trace.steps if s.stage == "rerank"]
    assert len(rerank_steps) == 1
    step = rerank_steps[0]
    assert step.tier == "skeleton"
    assert step.action == "deterministic"
    assert step.tokens_in == 0


async def test_focus_workflow_rerank_runs_on_localization_retry(
    tmp_path, parser_bench_submodule_present
):
    """When `retry_localization` re-runs localize, the rerank should also
    re-fire — the new region set deserves the same query-conditioned
    scoring as the initial pass."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")

    reasoner = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.9}')
    rerank_client = _FakeClient(
        '{"regions": [{"region_id": "r0_p3", "relevance": 0.5, "needed_for": "primary"}]}'
    )
    verifier = _ScriptedClient(
        [
            _verdict_json(supported=False, next_action="retry_localization"),
            _verdict_json(supported=True, next_action="accept"),
        ]
    )
    workflow = FocusWorkflow(
        backend_client=reasoner,
        tier_router=_FakeTierRouter(localizer_rerank=rerank_client, verifier=verifier),
        max_retries=2,
    )
    images = [tmp_path / "datasheet-A_page_0003_300dpi.png"]
    result = await workflow.run(_make_example(), images, protocol="focus")

    stage_counts = _stage_counts(result)
    # Initial pass + retry → localize + rerank both run twice.
    assert stage_counts["localize"] == 2
    assert stage_counts["rerank"] == 2
    # Rerank LLM was called twice (once per localize pass).
    assert len(rerank_client.calls) == 2


# ---------------------------------------------------------------------------
# Phase 2 / Phase 3: SimpleBaselineAgent prompt enrichment
# ---------------------------------------------------------------------------


async def test_simple_agent_prompt_includes_page_mapping(tmp_path, parser_bench_submodule_present):
    """Single image at page 50 → user prompt mentions 'page 50'."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    from focusparse.pipeline.workflow import SimpleBaselineAgent

    client = _FakeClient('{"answer": "5.5", "citations": []}')
    agent = SimpleBaselineAgent(backend_client=client, protocol="full_doc")
    img = tmp_path / "Arm_EE382N_4_page_0050_300dpi.png"
    img.write_bytes(b"fake")

    await agent.run(_make_example(), [img], image_pages=[50])

    prompt = client.calls[0]["prompt"]
    assert "page 50" in prompt
    # Sanity: the question is still in the prompt
    assert "supply voltage" in prompt


async def test_simple_agent_prompt_lists_multi_image_page_mapping(
    tmp_path, parser_bench_submodule_present
):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    from focusparse.pipeline.workflow import SimpleBaselineAgent

    client = _FakeClient('{"answer": "5.5", "citations": []}')
    agent = SimpleBaselineAgent(backend_client=client, protocol="full_doc")

    await agent.run(_make_example(), [tmp_path / "a.png", tmp_path / "b.png"], image_pages=[50, 12])

    prompt = client.calls[0]["prompt"]
    assert "image 1 = page 50" in prompt
    assert "image 2 = page 12" in prompt


async def test_simple_agent_prompt_omits_page_mapping_when_none(
    tmp_path, parser_bench_submodule_present
):
    """Backwards compat: legacy callers (no image_pages) get the bare question."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    from focusparse.pipeline.workflow import SimpleBaselineAgent

    client = _FakeClient('{"answer": "5.5", "citations": []}')
    agent = SimpleBaselineAgent(backend_client=client, protocol="full_doc")

    await agent.run(_make_example(), [tmp_path / "a.png"])

    prompt = client.calls[0]["prompt"]
    assert "page" not in prompt.split("\n")[0]  # First line is just the question.


async def test_simple_agent_prompt_includes_numeric_format_hint(
    tmp_path, parser_bench_submodule_present
):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    from focusparse.pipeline.workflow import SimpleBaselineAgent

    client = _FakeClient('{"answer": "5.5", "citations": []}')
    agent = SimpleBaselineAgent(backend_client=client, protocol="full_doc")

    # _make_example sets answer_type='numeric'
    await agent.run(_make_example(), [tmp_path / "a.png"])

    prompt = client.calls[0]["prompt"]
    assert "single number" in prompt.lower()
    assert "requested unit" in prompt.lower()


async def test_simple_agent_prompt_includes_exact_match_hint(
    tmp_path, parser_bench_submodule_present
):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    from focusparse._parser_bench import AnswerType
    from focusparse.pipeline.workflow import SimpleBaselineAgent

    client = _FakeClient('{"answer": "0x44", "citations": []}')
    agent = SimpleBaselineAgent(backend_client=client, protocol="full_doc")

    ex = _make_example().model_copy(update={"answer_type": AnswerType.EXACT_MATCH})
    await agent.run(ex, [tmp_path / "a.png"])

    prompt = client.calls[0]["prompt"]
    assert "exact label" in prompt.lower()
    assert "only the final exact answer" in prompt.lower()


async def test_simple_agent_prompt_includes_boolean_hint(tmp_path, parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    from focusparse._parser_bench import AnswerType
    from focusparse.pipeline.workflow import SimpleBaselineAgent

    client = _FakeClient('{"answer": "yes", "citations": []}')
    agent = SimpleBaselineAgent(backend_client=client, protocol="full_doc")

    ex = _make_example().model_copy(update={"answer_type": AnswerType.BOOLEAN})
    await agent.run(ex, [tmp_path / "a.png"])

    prompt = client.calls[0]["prompt"]
    assert "yes" in prompt.lower() and "no" in prompt.lower()


# ---------------------------------------------------------------------------
# Phase 2 of headline-table plan: --tool-set minimal | full
# ---------------------------------------------------------------------------


async def test_workflow_rejects_unknown_tool_set(parser_bench_submodule_present):
    """Defensive: tool_set outside {minimal, full} fails fast at construction."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")
    client = _FakeClient('{"answer": "x", "citations": []}')
    with pytest.raises(ValueError, match="tool_set"):
        FocusWorkflow(backend_client=client, tool_set="medium")


async def test_workflow_minimal_tool_set_skips_expand_context(
    tmp_path, parser_bench_submodule_present
):
    """tool_set=minimal records a passthrough expand_context step (tier=skipped)."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")

    client = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.9}')
    workflow = FocusWorkflow(backend_client=client, tool_set="minimal")
    images = [tmp_path / "datasheet-A_page_0003_300dpi.png"]
    result = await workflow.run(_make_example(), images, protocol="focus")

    assert result.telemetry["available_tools"] == ["inspect_region", "get_text_layer"]

    expand_steps = [s for s in result.trace.steps if s.stage == "expand_context"]
    assert len(expand_steps) == 1
    step = expand_steps[0]
    assert step.tier == "skipped"
    assert step.action == "passthrough"
    assert step.args.get("reason") == "tool_set=minimal"


async def test_workflow_full_tool_set_runs_expand_context(tmp_path, parser_bench_submodule_present):
    """tool_set=full (default) runs the real expand_context with deterministic tier."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")

    client = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.9}')
    workflow = FocusWorkflow(backend_client=client, tool_set="full")
    images = [tmp_path / "datasheet-A_page_0003_300dpi.png"]
    result = await workflow.run(_make_example(), images, protocol="focus")

    assert result.telemetry["available_tools"] == [
        "inspect_region",
        "get_text_layer",
        "expand_context",
        "run_python",
    ]

    expand_steps = [s for s in result.trace.steps if s.stage == "expand_context"]
    assert len(expand_steps) == 1
    step = expand_steps[0]
    assert step.tier in ("deterministic", "skeleton")
    assert step.action != "passthrough"


async def test_workflow_minimal_tool_set_forces_auto_zoom_off(
    parser_bench_submodule_present,
):
    """auto_zoom=True + tool_set=minimal → auto_zoom is silently disabled
    (run_python is one of the tools removed in the +2-tools belt)."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")
    client = _FakeClient('{"answer": "x", "citations": []}')
    workflow = FocusWorkflow(backend_client=client, auto_zoom=True, tool_set="minimal")
    assert workflow.auto_zoom is False


async def test_workflow_full_tool_set_respects_auto_zoom(
    parser_bench_submodule_present,
):
    """auto_zoom=True + tool_set=full → auto_zoom stays on."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")
    client = _FakeClient('{"answer": "x", "citations": []}')
    workflow = FocusWorkflow(backend_client=client, auto_zoom=True, tool_set="full")
    assert workflow.auto_zoom is True


# ---------------------------------------------------------------------------
# Sprint Phase 1 (2026-05-04): use_react_inspector flag
# ---------------------------------------------------------------------------


async def test_workflow_react_inspector_default_off(parser_bench_submodule_present):
    """use_react_inspector defaults to False; inspect step keeps the
    deterministic_inspector tool name (no behavior change for v1 callers)."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")
    client = _FakeClient('{"answer": "x", "citations": []}')
    workflow = FocusWorkflow(backend_client=client)
    assert workflow.use_react_inspector is False
    images = [Path("datasheet-A_page_0003_300dpi.png")]
    result = await workflow.run(_make_example(), images, protocol="focus")
    inspect_steps = [s for s in result.trace.steps if s.stage == "inspect"]
    assert len(inspect_steps) == 1
    assert inspect_steps[0].tool == "deterministic_inspector"


# ---------------------------------------------------------------------------
# Phase 2 (2026-05-11 harness-growth): hard-case dispatch unit tests
# ---------------------------------------------------------------------------


def _hgs_plan(family: str = "spec_table_cell_retrieval", budget: str = "easy_local"):
    """Lightweight PlanEvent factory for _should_use_react_inspector tests."""
    from focusparse.pipeline.events import PlanEvent

    return PlanEvent(
        question_family=family,
        evidence_types=["table"],
        budget_class=budget,
        routing_policy="text_first",
        max_tool_calls=8,
        max_crops=4,
        max_vlm_calls=2,
    )


def _hgs_regions(*, top_relevance: float | None = None):
    """Lightweight RegionsEvent factory."""
    from focusparse.pipeline.events import RegionCandidate, RegionsEvent

    if top_relevance is None:
        return RegionsEvent(candidates=[])
    return RegionsEvent(
        candidates=[
            RegionCandidate(
                region_id="r0",
                page=1,
                bbox_norm=(0.1, 0.2, 0.3, 0.4),
                region_type="table",
                score=0.9,
                relevance=top_relevance,
            )
        ]
    )


def test_should_use_react_inspector_fires_on_highres_tiny_budget():
    """Trigger A (Phase 5): highres_tiny budget fires alone — strongest
    single signal because the planner explicitly flagged tiny-region/fine-
    detail content."""
    plan = _hgs_plan(family="spec_table_cell_retrieval", budget="highres_tiny")
    assert _should_use_react_inspector(plan, _hgs_regions()) is True


def test_should_use_react_inspector_fires_on_fine_detail_family_AND_low_rerank():
    """Trigger B (Phase 5): fine-detail family AND low rerank confidence.
    Both signals must hold — Phase 2 fired on either alone and the slice
    analysis showed that was net-negative (-3.9pp on the dispatched slice).
    """
    plan = _hgs_plan(family="axis_value_interpolation")
    # AND-gated: family signal + low rerank → fires
    assert _should_use_react_inspector(plan, _hgs_regions(top_relevance=0.3)) is True


def test_should_use_react_inspector_skips_fine_detail_family_when_rerank_is_high():
    """Phase 5 tightening: fine-detail family alone is NOT enough.
    Previously (Phase 2 OR-gated) this would have fired and lost on the
    dispatcher slice. Now stays deterministic when the reranker has
    confidence in a region."""
    plan = _hgs_plan(family="axis_value_interpolation")
    assert _should_use_react_inspector(plan, _hgs_regions(top_relevance=0.8)) is False


def test_should_use_react_inspector_skips_low_rerank_when_family_is_not_fine_detail():
    """Phase 5 tightening: low rerank alone is NOT enough. A vanilla
    family like spec_table_cell_retrieval with low rerank confidence
    stays on the deterministic path — Phase 4 showed those examples
    didn't benefit from the LLM dispatcher."""
    plan = _hgs_plan(family="spec_table_cell_retrieval", budget="easy_local")
    assert _should_use_react_inspector(plan, _hgs_regions(top_relevance=0.3)) is False


def test_should_use_react_inspector_skips_on_easy_examples():
    """Vanilla family + easy_local budget + decent rerank → stay
    deterministic. This is the cost-saving case."""
    plan = _hgs_plan(family="spec_table_cell_retrieval", budget="easy_local")
    assert _should_use_react_inspector(plan, _hgs_regions(top_relevance=0.8)) is False


def test_should_use_react_inspector_skips_fine_detail_family_when_no_rerank_signal():
    """Phase 5: fine-detail family alone WITHOUT a rerank signal does
    NOT fire. The AND gate requires both signals; missing one (either
    direction) skips."""
    plan = _hgs_plan(family="axis_value_interpolation", budget="easy_local")
    from focusparse.pipeline.events import RegionCandidate, RegionsEvent

    regions = RegionsEvent(
        candidates=[
            RegionCandidate(
                region_id="r0",
                page=1,
                bbox_norm=(0.1, 0.2, 0.3, 0.4),
                region_type="picture",
                score=0.9,
                relevance=None,  # reranker didn't run
            )
        ]
    )
    assert _should_use_react_inspector(plan, regions) is False


def _hard_case_planner_client(family: str = "min_typ_max_disambiguation") -> _FakeClient:
    """Planner client returning the highres_tiny budget so the Phase 5
    AND-gated dispatcher fires on the strongest single signal (trigger A)
    without needing a reranker tier wired into the test harness.

    Phase 5 (2026-05-11 evening) tightened the trigger from OR to AND for
    the family+rerank pair. The family alone is no longer sufficient; tests
    that want the react path now use highres_tiny so they don't have to
    also mock a reranker emitting low-relevance regions.
    """
    return _FakeClient(
        '{"question_family": "' + family + '", "evidence_types": ["table", "footnote"], '
        '"budget_class": "highres_tiny", "routing_policy": "text_first"}',
        tokens_in=90,
        tokens_out=20,
    )


async def test_workflow_react_inspector_falls_back_without_tier_router(
    parser_bench_submodule_present,
):
    """Phase 2 (2026-05-11): with use_react_inspector=True AND a hard-case
    trigger (fine-detail family) but no inspector_dispatch tier client, the
    react path runs and falls back to deterministic top-N internally — trace
    shows `react_inspector` tool with `fallback_used=True` and
    `inspector_path=react_hard_case`."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")
    client = _FakeClient('{"answer": "x", "citations": []}')
    # Planner client emits a fine-detail family so the hard-case dispatcher
    # fires. Without a planner client, the deterministic fallback returns
    # `question_family="unknown"` and the dispatcher (correctly) skips ReAct.
    planner = _hard_case_planner_client()
    workflow = FocusWorkflow(
        backend_client=client,
        tier_router=_FakeTierRouter(planner=planner),
        use_react_inspector=True,
    )
    images = [Path("datasheet-A_page_0003_300dpi.png")]
    result = await workflow.run(_make_example(), images, protocol="focus")
    inspect_steps = [s for s in result.trace.steps if s.stage == "inspect"]
    assert len(inspect_steps) == 1
    step = inspect_steps[0]
    assert step.tool == "react_inspector"
    assert step.args.get("fallback_used") is True
    assert step.args.get("inspector_path") == "react_hard_case"


async def test_workflow_react_inspector_uses_tier_router_when_present(
    parser_bench_submodule_present,
):
    """Phase 2: with hard-case trigger AND inspector_dispatch tier resolving to
    a real client, the react inspector dispatches via LLM (tier=mid,
    action=llm_call)."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")
    reasoner = _FakeClient('{"answer": "x", "citations": []}')
    inspector = _FakeClient(
        '{"thought": "pick the chart", "plan": [{"region_idx": 0, "mode": "image"}]}'
    )
    planner = _hard_case_planner_client()

    workflow = FocusWorkflow(
        backend_client=reasoner,
        tier_router=_FakeTierRouter(planner=planner, inspector_dispatch=inspector),
        use_react_inspector=True,
    )
    images = [Path("datasheet-A_page_0003_300dpi.png")]
    result = await workflow.run(_make_example(), images, protocol="focus")
    inspect_steps = [s for s in result.trace.steps if s.stage == "inspect"]
    step = inspect_steps[0]
    assert step.tool == "react_inspector"
    assert step.action == "llm_call"
    assert step.tier == "mid"
    assert step.args.get("fallback_used") is False
    assert step.args.get("inspector_path") == "react_hard_case"
    assert step.tokens_in > 0  # the inspector LLM call was recorded


async def test_workflow_react_inspector_skipped_for_easy_examples(
    parser_bench_submodule_present,
):
    """Phase 2 (2026-05-11): with use_react_inspector=True but NO hard-case
    trigger (vanilla family, easy_local budget, no low rerank), the workflow
    stays on the deterministic floor. This is the whole point of hard-case
    dispatch — easy examples don't pay the LLM-inspector cost."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")
    reasoner = _FakeClient('{"answer": "x", "citations": []}')
    # Planner returns a NON-fine-detail family + easy_local budget.
    planner = _FakeClient(
        '{"question_family": "spec_table_cell_retrieval", '
        '"evidence_types": ["table"], '
        '"budget_class": "easy_local", '
        '"routing_policy": "text_first"}',
        tokens_in=80,
        tokens_out=20,
    )
    inspector = _FakeClient(
        '{"thought": "should not run", "plan": []}',
        tokens_in=999,
        tokens_out=999,
    )
    workflow = FocusWorkflow(
        backend_client=reasoner,
        tier_router=_FakeTierRouter(planner=planner, inspector_dispatch=inspector),
        use_react_inspector=True,
    )
    images = [Path("datasheet-A_page_0003_300dpi.png")]
    result = await workflow.run(_make_example(), images, protocol="focus")
    inspect_steps = [s for s in result.trace.steps if s.stage == "inspect"]
    assert len(inspect_steps) == 1
    step = inspect_steps[0]
    # Deterministic path — the LLM-inspector was NOT called even though the flag was on.
    assert step.tool == "deterministic_inspector"
    assert step.args.get("inspector_path") == "deterministic"
    assert inspector.calls == [], (
        "inspector_dispatch LLM was called on an easy example — hard-case dispatch is over-broad"
    )
