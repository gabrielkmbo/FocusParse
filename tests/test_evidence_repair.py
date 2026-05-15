"""Same-evidence repair context tests."""

from focusparse.evidence.packet import EvidencePacket, PacketProvenance
from focusparse.pipeline.events import AnswerEvent, EvidenceEvent, QuestionEvent
from focusparse.pipeline.evidence_repair import build_same_evidence_repair_context


def _packet(
    *,
    packet_id: str = "pkt_000",
    region_type: str | None = "Table",
    text: str | None = None,
    chart_csv: str | None = None,
) -> EvidencePacket:
    return EvidencePacket(
        packet_id=packet_id,
        page=5,
        bbox_norm=(0.1, 0.2, 0.8, 0.9),
        region_type=region_type,
        page_thumbnail_ref="/cache/pages/p5.png",
        local_crop_ref="/cache/crops/pkt.png",
        text_layer_snippet=text,
        chart_csv=chart_csv,
        provenance=PacketProvenance(tool="t", args_hash=""),
    )


def _question(text: str, *, answer_type: str = "exact_match") -> QuestionEvent:
    return QuestionEvent(
        example_id="ex",
        question=text,
        doc_id="doc",
        pages_available=1,
        answer_type=answer_type,
    )


def test_table_repair_context_surfaces_source_and_output_rows() -> None:
    packet = _packet(
        text=(
            "Products net sales 297,392 220,747 198,270\n"
            "Services net sales 96,169 85,200 78,129\n"
            "Gross margin 169,148 180,683 170,782"
        )
    )
    context = build_same_evidence_repair_context(
        _question(
            "For the year in which Products net sales reached their minimum among "
            "the three years shown, what was the corresponding Gross margin value?"
        ),
        EvidenceEvent(packets=[packet]),
        AnswerEvent(answer="169,148; minimum", citations=["pkt_000"], confidence=0.7),
        ["wrong_row_risk"],
    )

    assert "Same-evidence repair context" in context
    assert "Products net sales" in context
    assert "Gross margin" in context
    assert "Services net sales" not in context


def test_checkbox_repair_context_prefers_checkbox_lines() -> None:
    packet = _packet(
        text=(
            "Large accelerated filer Yes [X] No [ ]\n"
            "Accelerated filer Yes [ ] No [X]\n"
            "Filed all required reports Yes [X] No [ ]"
        )
    )
    context = build_same_evidence_repair_context(
        _question(
            "Based on the check marks, does the registrant qualify as a large "
            "accelerated filer and has it filed all required reports?",
            answer_type="boolean",
        ),
        EvidenceEvent(packets=[packet]),
        AnswerEvent(answer="no", citations=["pkt_000"], confidence=0.7),
        ["checkbox_binding_risk"],
    )

    assert "Large accelerated filer Yes [X] No [ ]" in context
    assert "Filed all required reports Yes [X] No [ ]" in context


def test_chart_repair_context_surfaces_chart_csv_and_binding_lines() -> None:
    packet = _packet(
        region_type="chart",
        text=(
            "Context [caption]: Figure 2. Revenue by product line\n"
            "Legend: blue line Products, gray line Services\n"
            "Y-axis: net sales in millions"
        ),
        chart_csv="series,year,value\nProducts,2024,297392\nServices,2024,96169",
    )
    context = build_same_evidence_repair_context(
        _question("Which series has the higher net sales in 2024?"),
        EvidenceEvent(packets=[packet]),
        AnswerEvent(answer="Services", citations=["pkt_000"], confidence=0.7),
        ["legend_binding_risk"],
    )

    assert "Chart binding lines" in context
    assert "chart_csv=series,year,value" in context
    assert "Legend: blue line Products" in context
    assert "Y-axis: net sales" in context
