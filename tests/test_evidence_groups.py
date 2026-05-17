"""Tests for grouped evidence prompt rendering."""

from focusparse.evidence.packet import EvidencePacket, PacketProvenance
from focusparse.pipeline.answer_contract import build_answer_contract
from focusparse.pipeline.evidence_groups import build_evidence_groups, render_evidence_groups


def _packet(
    *,
    packet_id: str = "pkt_000",
    region_type: str | None = None,
    text: str | None = None,
    linked_neighbor_types: list[str] | None = None,
) -> EvidencePacket:
    return EvidencePacket(
        packet_id=packet_id,
        page=5,
        bbox_norm=(0.1, 0.2, 0.8, 0.9),
        region_type=region_type,
        page_thumbnail_ref="/cache/pages/p5.png",
        local_crop_ref="/cache/crops/pkt.png",
        text_layer_snippet=text,
        linked_neighbor_types=linked_neighbor_types or [],
        provenance=PacketProvenance(tool="t", args_hash=""),
    )


def test_table_group_renders_row_headers_units_and_notes() -> None:
    contract = build_answer_contract(
        "Which value (min, typ, or max) should be used, and what voltage?",
        answer_type="exact_match",
        domain="datasheet",
    )
    packet = _packet(
        region_type="Table",
        text=(
            "Parameter Test Conditions Min Typ Max Unit\n"
            "FB Error Comparator Threshold DEM -40C to 85C 0.697 0.704 0.711 V\n"
            "Context [section-header]: Electrical Characteristics\n"
            "Context [caption_context]: Vcc = 5V, Ta = 25C unless otherwise specified\n"
            "Context [footnote]: Note 5 applies to the DEM condition"
        ),
    )

    groups = build_evidence_groups([packet], question_text="FB Error Comparator", contract=contract)
    rendered = render_evidence_groups(groups, contract=contract)

    assert groups[0].group_kind == "table"
    assert "table row, its row label, column headers, units, test conditions, and notes" in rendered
    assert "FB Error Comparator Threshold" in rendered
    assert "header='Electrical Characteristics'" in rendered
    assert "caption='Vcc = 5V" in rendered
    assert "footnote='Note 5 applies" in rendered
    assert "preserve min/typ/max labels" in rendered


def test_chart_group_binds_legend_axis_caption_without_chart_to_table() -> None:
    contract = build_answer_contract(
        "Which country experienced the largest increase between markers a and c?",
        answer_type="exact_match",
        domain="finance",
        question_family="legend_series_binding",
    )
    packet = _packet(
        region_type="Picture",
        text="blue line rises between marker a and marker c\nContext [caption]: Figure 2",
        linked_neighbor_types=["legend", "axis-label"],
    )

    groups = build_evidence_groups([packet], question_text="largest increase", contract=contract)
    rendered = render_evidence_groups(groups, contract=contract)

    assert groups[0].group_kind == "chart"
    assert "plot area, legend/series style, axes/ticks, caption, and footnotes" in rendered
    assert "legend='(attached image/crop)'" in rendered
    assert "axis='(attached image/crop)'" in rendered
    assert "check series/legend/axis binding" in rendered


def test_group_render_marks_verifier_cited_packets() -> None:
    groups = build_evidence_groups(
        [
            _packet(packet_id="pkt_000", text="answer row"),
            _packet(packet_id="pkt_001", text="distractor row"),
        ]
    )

    rendered = render_evidence_groups(groups, cited_packet_ids={"pkt_001"})

    assert "primary=pkt_000" in rendered
    assert "primary=pkt_001" in rendered
    assert "primary=pkt_000 page=5" in rendered
    assert "primary=pkt_001 page=5" in rendered
    assert (
        "primary=pkt_000 page=5 bbox=[0.100, 0.200, 0.800, 0.900] region=unknown cited_by_answer=no"
        in rendered
    )
    assert (
        "primary=pkt_001 page=5 bbox=[0.100, 0.200, 0.800, 0.900] region=unknown cited_by_answer=yes"
        in rendered
    )
