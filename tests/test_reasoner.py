"""Reasoner-side tests focused on multi-scale evidence packet handling.

The full end-to-end reasoner path is covered in test_workflow.py; this
file pins the contract that when EvidencePacket.multi_scale_crops is
populated, the LLM sees BOTH the tight and context crops as separate
image inputs (and is told so in the packet descriptor line).
"""

from __future__ import annotations

from pathlib import Path

from focusparse.evidence.packet import (
    CropRef,
    EvidencePacket,
    PacketProvenance,
)
from focusparse.pipeline.events import EvidenceEvent
from focusparse.pipeline.reasoner import (
    _MAX_PACKET_TEXT_CHARS,
    _collect_packet_images,
    _format_hint,
    _parse_reasoner_response,
    _render_packet_line,
)


def _packet(
    *,
    packet_id: str = "pkt_000",
    page: int = 3,
    bbox: tuple[float, float, float, float] = (0.1, 0.2, 0.5, 0.6),
    local_crop_ref: str = "/cache/crops/abc.png",
    page_thumbnail_ref: str = "/cache/pages/p3.png",
    multi_scale: list[CropRef] | None = None,
    linked_crop_refs: list[str] | None = None,
    linked_neighbor_types: list[str] | None = None,
    text_layer_snippet: str | None = None,
    ocr_snippet: str | None = None,
) -> EvidencePacket:
    return EvidencePacket(
        packet_id=packet_id,
        page=page,
        bbox_norm=bbox,
        page_thumbnail_ref=page_thumbnail_ref,
        local_crop_ref=local_crop_ref,
        multi_scale_crops=multi_scale or [],
        linked_crop_refs=linked_crop_refs or [],
        linked_neighbor_types=linked_neighbor_types or [],
        text_layer_snippet=text_layer_snippet,
        ocr_snippet=ocr_snippet,
        provenance=PacketProvenance(tool="t", args_hash=""),
    )


# ---------------------------------------------------------------------------
# _collect_packet_images
# ---------------------------------------------------------------------------


def test_collect_packet_images_uses_local_crop_ref_when_no_multi_scale() -> None:
    ev = EvidenceEvent(packets=[_packet(local_crop_ref="/cache/a.png")])
    images = _collect_packet_images(ev)
    assert images == [Path("/cache/a.png")]


def test_collect_packet_images_falls_back_to_page_thumbnail() -> None:
    ev = EvidenceEvent(packets=[_packet(local_crop_ref="", page_thumbnail_ref="/cache/p.png")])
    images = _collect_packet_images(ev)
    assert images == [Path("/cache/p.png")]


def test_collect_packet_images_dedupes_repeated_refs() -> None:
    ev = EvidenceEvent(
        packets=[
            _packet(packet_id="pkt_000", local_crop_ref="/cache/same.png"),
            _packet(packet_id="pkt_001", local_crop_ref="/cache/same.png"),
        ]
    )
    images = _collect_packet_images(ev)
    assert images == [Path("/cache/same.png")]


def test_collect_packet_images_uses_multi_scale_when_present() -> None:
    """When multi_scale_crops is populated, both tight + context refs surface."""
    ev = EvidenceEvent(
        packets=[
            _packet(
                local_crop_ref="/cache/tight.png",
                multi_scale=[
                    CropRef(ref="/cache/tight.png", bbox_norm=(0.1, 0.2, 0.5, 0.6), scale="tight"),
                    CropRef(
                        ref="/cache/context.png", bbox_norm=(0.0, 0.0, 0.8, 0.9), scale="context"
                    ),
                ],
            )
        ]
    )
    images = _collect_packet_images(ev)
    assert images == [Path("/cache/tight.png"), Path("/cache/context.png")]


def test_collect_packet_images_dedupes_across_multi_scale() -> None:
    ev = EvidenceEvent(
        packets=[
            _packet(
                packet_id="pkt_000",
                multi_scale=[
                    CropRef(ref="/cache/A.png", bbox_norm=(0, 0, 1, 1), scale="tight"),
                    CropRef(ref="/cache/B.png", bbox_norm=(0, 0, 1, 1), scale="context"),
                ],
            ),
            _packet(
                packet_id="pkt_001",
                multi_scale=[
                    CropRef(ref="/cache/A.png", bbox_norm=(0, 0, 1, 1), scale="tight"),
                    CropRef(ref="/cache/C.png", bbox_norm=(0, 0, 1, 1), scale="context"),
                ],
            ),
        ]
    )
    images = _collect_packet_images(ev)
    # /cache/A.png is shared between the two packets and dedups; B and C add.
    assert images == [Path("/cache/A.png"), Path("/cache/B.png"), Path("/cache/C.png")]


def test_collect_packet_images_mixed_legacy_and_multi_scale() -> None:
    """One packet with multi_scale, one without — both contribute their refs."""
    ev = EvidenceEvent(
        packets=[
            _packet(
                packet_id="pkt_000",
                multi_scale=[
                    CropRef(ref="/cache/A.png", bbox_norm=(0, 0, 1, 1), scale="tight"),
                    CropRef(ref="/cache/B.png", bbox_norm=(0, 0, 1, 1), scale="context"),
                ],
            ),
            _packet(packet_id="pkt_001", local_crop_ref="/cache/legacy.png"),
        ]
    )
    images = _collect_packet_images(ev)
    assert images == [Path("/cache/A.png"), Path("/cache/B.png"), Path("/cache/legacy.png")]


# ---------------------------------------------------------------------------
# Path A (2026-05-06): linked_crop_refs reach the reasoner as images.
# Pre-Path-A this was dead code; the 2026-05-06 memory entry has the diagnosis.
# ---------------------------------------------------------------------------


def test_collect_packet_images_includes_linked_crop_refs() -> None:
    """A packet with 2 linked neighbor crops surfaces them after the primary."""
    ev = EvidenceEvent(
        packets=[
            _packet(
                local_crop_ref="/cache/primary.png",
                linked_crop_refs=["/cache/caption.png", "/cache/footnote.png"],
                linked_neighbor_types=["caption", "footnote"],
            )
        ]
    )
    images = _collect_packet_images(ev)
    # Order is primary → linked, so the reasoner reads "this is the focus,
    # then the context."
    assert images == [
        Path("/cache/primary.png"),
        Path("/cache/caption.png"),
        Path("/cache/footnote.png"),
    ]


def test_collect_packet_images_dedupes_neighbors_across_packets() -> None:
    """A neighbor ref shared between two packets appears once in the image list."""
    ev = EvidenceEvent(
        packets=[
            _packet(
                packet_id="pkt_000",
                local_crop_ref="/cache/a.png",
                linked_crop_refs=["/cache/shared_caption.png"],
                linked_neighbor_types=["caption"],
            ),
            _packet(
                packet_id="pkt_001",
                local_crop_ref="/cache/b.png",
                linked_crop_refs=["/cache/shared_caption.png", "/cache/footnote.png"],
                linked_neighbor_types=["caption", "footnote"],
            ),
        ]
    )
    images = _collect_packet_images(ev)
    assert images == [
        Path("/cache/a.png"),
        Path("/cache/shared_caption.png"),
        Path("/cache/b.png"),
        Path("/cache/footnote.png"),
    ]


def test_collect_packet_images_skips_empty_neighbor_refs() -> None:
    """Empty-string entries in linked_crop_refs are filtered out."""
    ev = EvidenceEvent(
        packets=[
            _packet(
                local_crop_ref="/cache/primary.png",
                linked_crop_refs=["", "/cache/real.png", ""],
                linked_neighbor_types=["caption", "footnote", "title"],
            )
        ]
    )
    images = _collect_packet_images(ev)
    assert images == [Path("/cache/primary.png"), Path("/cache/real.png")]


def test_collect_packet_images_neighbors_follow_multi_scale() -> None:
    """When BOTH multi_scale_crops AND linked_crop_refs are populated, the
    image order is: tight → context → linked. (Multi-scale primaries first,
    then expand_context's neighbors.)"""
    ev = EvidenceEvent(
        packets=[
            _packet(
                multi_scale=[
                    CropRef(ref="/cache/tight.png", bbox_norm=(0.1, 0.2, 0.5, 0.6), scale="tight"),
                    CropRef(ref="/cache/ctx.png", bbox_norm=(0.0, 0.0, 0.8, 0.9), scale="context"),
                ],
                linked_crop_refs=["/cache/caption.png"],
                linked_neighbor_types=["caption"],
            )
        ]
    )
    images = _collect_packet_images(ev)
    assert images == [
        Path("/cache/tight.png"),
        Path("/cache/ctx.png"),
        Path("/cache/caption.png"),
    ]


def test_collect_packet_images_skips_text_only_header_neighbors() -> None:
    """Header-like neighbors with extracted text stay in prompt text, not images."""
    ev = EvidenceEvent(
        packets=[
            _packet(
                local_crop_ref="/cache/primary.png",
                linked_crop_refs=["/cache/header.png", "/cache/caption.png"],
                linked_neighbor_types=["section-header", "caption"],
                text_layer_snippet=(
                    "Context [section-header]: Electrical Characteristics\n"
                    "Context [caption]: Figure 4. Load transient response"
                ),
            )
        ]
    )
    images = _collect_packet_images(ev)
    assert images == [Path("/cache/primary.png"), Path("/cache/caption.png")]


def test_collect_packet_images_keeps_header_neighbor_without_extracted_text() -> None:
    """Do not hide a header crop unless expand actually recovered its text."""
    ev = EvidenceEvent(
        packets=[
            _packet(
                local_crop_ref="/cache/primary.png",
                linked_crop_refs=["/cache/header.png"],
                linked_neighbor_types=["section-header"],
                text_layer_snippet="Main packet text only",
            )
        ]
    )
    images = _collect_packet_images(ev)
    assert images == [Path("/cache/primary.png"), Path("/cache/header.png")]


# ---------------------------------------------------------------------------
# _render_packet_line
# ---------------------------------------------------------------------------


def test_render_packet_line_legacy_packet() -> None:
    """No multi_scale → no scale annotation."""
    line = _render_packet_line(_packet(packet_id="pkt_000"))
    assert "pkt_000" in line
    assert "page 3" in line
    assert "image scales" not in line


def test_render_packet_line_multi_scale_packet() -> None:
    """multi_scale → annotation tells reasoner how many crops it will see."""
    p = _packet(
        multi_scale=[
            CropRef(ref="/a.png", bbox_norm=(0, 0, 1, 1), scale="tight"),
            CropRef(ref="/b.png", bbox_norm=(0, 0, 1, 1), scale="context"),
        ]
    )
    line = _render_packet_line(p)
    assert "2 image scales in order" in line
    assert "tight [0.000, 0.000, 1.000, 1.000]" in line
    assert "context [0.000, 0.000, 1.000, 1.000]" in line


def test_render_packet_line_names_zoomed_scale() -> None:
    p = _packet(
        multi_scale=[
            CropRef(ref="/a.png", bbox_norm=(0.1, 0.2, 0.5, 0.6), scale="tight"),
            CropRef(ref="/b.png", bbox_norm=(0.1, 0.2, 0.5, 0.6), scale="zoomed"),
        ]
    )
    line = _render_packet_line(p)
    assert "zoomed [0.100, 0.200, 0.500, 0.600]" in line


def test_render_packet_line_names_chart_context_scale() -> None:
    """chart_context is a distinct wider crop, not a generic neighbor."""
    p = _packet(
        multi_scale=[
            CropRef(ref="/a.png", bbox_norm=(0.1, 0.2, 0.4, 0.5), scale="tight"),
            CropRef(
                ref="/b.png",
                bbox_norm=(0.0, 0.1, 0.6, 0.7),
                scale="chart_context",
            ),
        ]
    )
    line = _render_packet_line(p)
    assert "chart_context [0.000, 0.100, 0.600, 0.700]" in line
    assert "wider crop for axes, legends, and curve geometry" in line


def test_render_packet_line_single_scale_does_not_annotate() -> None:
    """Multi-scale list of length 1 is degenerate (just tight); no annotation."""
    p = _packet(
        multi_scale=[
            CropRef(ref="/a.png", bbox_norm=(0, 0, 1, 1), scale="tight"),
        ]
    )
    line = _render_packet_line(p)
    assert "image scales" not in line


def test_render_packet_line_includes_native_text_snippet() -> None:
    p = _packet(text_layer_snippet="VCC max 3.6 V\nConditions: TA = 25 C")
    line = _render_packet_line(p)
    assert "Extracted text" in line
    assert "VCC max 3.6 V Conditions: TA = 25 C" in line


def test_render_packet_line_falls_back_to_ocr_snippet() -> None:
    p = _packet(ocr_snippet="axis label: Gross margin")
    line = _render_packet_line(p)
    assert "axis label: Gross margin" in line


def test_render_packet_line_prefers_native_text_over_ocr() -> None:
    p = _packet(text_layer_snippet="native text", ocr_snippet="ocr text")
    line = _render_packet_line(p)
    assert "native text" in line
    assert "ocr text" not in line


def test_render_packet_line_truncates_long_text_snippet() -> None:
    p = _packet(text_layer_snippet="x" * (_MAX_PACKET_TEXT_CHARS + 20))
    line = _render_packet_line(p)
    assert ("x" * _MAX_PACKET_TEXT_CHARS) not in line
    assert "..." in line


def test_render_packet_line_focuses_long_table_text_on_question_terms() -> None:
    table_text = "\n".join(
        [
            "Part Number",
            "RT9187C 2.5 5.5 600 300 Enable Input Ultra-Low Noise SOT-23-5",
            "RT2519 2.2 6 1000 190 High PSRR Industrial Grade VDFN3x3-8A",
            "RTQ2510-QA 2.2 6 1000 190",
            "Enable Input Ultra-Low Noise High PSRR AEC-Q100",
            "VDFN3x3-8",
        ]
    )
    p = _packet(text_layer_snippet=table_text + "\n" + ("filler row\n" * 80))
    line = _render_packet_line(
        p,
        question_text=(
            "Which AEC-Q100 part with Enable Input, Ultra-Low Noise, "
            "and High PSRR has the lowest Iq, and what package is it?"
        ),
    )
    assert "RTQ2510-QA" in line
    assert "AEC-Q100" in line
    assert "VDFN3x3-8" in line
    assert "RT9187C" not in line


# ---------------------------------------------------------------------------
# Sprint Phase 3: chart_csv rendering in the prompt
# ---------------------------------------------------------------------------


def test_render_packet_line_includes_chart_csv_when_present() -> None:
    """Phase 3: chart_to_table CSV appears in a fenced code block."""
    p = _packet(
        local_crop_ref="/cache/chart.png",
    )
    p.chart_csv = "x_value,y_value\n0.0,2.5\n1.0,3.7"
    p.chart_extraction_confidence = 0.78
    line = _render_packet_line(p)
    assert "Chart extraction" in line
    assert "confidence=0.78" in line
    assert "```csv" in line
    assert "x_value,y_value" in line
    assert "0.0,2.5" in line


def test_render_packet_line_omits_chart_csv_when_none() -> None:
    p = _packet()
    line = _render_packet_line(p)
    assert "Chart extraction" not in line
    assert "```csv" not in line


def test_render_packet_line_chart_without_confidence_renders_advisory() -> None:
    p = _packet()
    p.chart_csv = "x_value,y_value\n5,10"
    p.chart_extraction_confidence = None
    line = _render_packet_line(p)
    assert "Chart extraction" in line
    assert "advisory" in line
    assert "confidence=" not in line


def test_numeric_format_hint_preserves_requested_units() -> None:
    hint = _format_hint("numeric")
    assert "single number" in hint
    assert "requested unit" in hint
    assert "% sign" in hint


def test_exact_match_format_hint_overrides_explain_wording() -> None:
    hint = _format_hint("exact_match")
    assert "only the final exact answer" in hint
    assert "Even if the question asks for an explanation" in hint
    assert "omit spaces around '='" in hint


def test_exact_match_format_hint_phase6a_tightening_rules_present() -> None:
    """Phase 6a (2026-05-11 evening): four extraction-format rules added
    based on the Phase 4 failure analysis. Each rule maps to a sampled
    failure pattern in the n=148 right-region-wrong bucket."""
    hint = _format_hint("exact_match")
    # Rule 1: no leading labels (Gross margin example)
    assert "Gross margin" in hint
    # Rule 2: no trailing descriptions (Reserved. RAZ. example)
    assert "Reserved" in hint
    # Rule 3: include all parts of multi-part answers (BLE / semicolons)
    assert "multi-part" in hint or "all parts" in hint.lower()
    # Rule 4: no conditional/alternative branches (HIVECS example)
    assert "conditional" in hint.lower() or "alternative" in hint.lower()
    # Existing bit-field rule preserved
    assert "[15:14]=b00" in hint


def test_exact_match_format_hint_keeps_explanatory_questions_complete() -> None:
    hint = _format_hint(
        "exact_match",
        question_text=(
            "Which country had the lowest Composite PMI value, and what is "
            "that value? Briefly explain how you distinguish it from the "
            "nearby rows."
        ),
    )

    assert "do NOT answer with only a bare label" in hint
    assert "one concise sentence" in hint


def test_exact_match_format_hint_does_not_expand_plain_lookup_questions() -> None:
    hint = _format_hint("exact_match", question_text="Which register contains HIVECS?")

    assert "do NOT answer with only a bare label" not in hint


def test_parse_reasoner_response_canonicalizes_bit_assignments() -> None:
    answer, citations, confidence = _parse_reasoner_response(
        (
            '{"answer":"[15:14] = b00; [8:5] = b1111; [4:3] = b11",'
            '"citations":["pkt_000"],"confidence":0.98}'
        ),
        valid_packet_ids={"pkt_000"},
    )

    assert answer == "[15:14]=b00, [8:5]=b1111, [4:3]=b11"
    assert citations == ["pkt_000"]
    assert confidence == 0.98


def test_parse_reasoner_response_canonicalizes_ppt_when_question_requests_percent() -> None:
    answer, citations, confidence = _parse_reasoner_response(
        '{"answer":"0ppt","citations":["pkt_000"],"confidence":0.8}',
        valid_packet_ids={"pkt_000"},
        question_text="What incorrect numeric percentage value might you report?",
    )

    assert answer == "0%"
    assert citations == ["pkt_000"]
    assert confidence == 0.8


def test_parse_reasoner_response_preserves_ppt_when_question_requests_points() -> None:
    answer, _citations, _confidence = _parse_reasoner_response(
        '{"answer":"2ppt","citations":[],"confidence":0.8}',
        valid_packet_ids=set(),
        question_text="What is the difference in percentage points?",
    )

    assert answer == "2ppt"


def test_parse_reasoner_response_adds_country_value_separator() -> None:
    answer, citations, confidence = _parse_reasoner_response(
        '{"answer":"France 49.9","citations":["pkt_000"],"confidence":0.96}',
        valid_packet_ids={"pkt_000"},
        question_text="Which country had the lowest PMI value, and what is that value?",
    )

    assert answer == "France, 49.9"
    assert citations == ["pkt_000"]
    assert confidence == 0.96


def test_parse_reasoner_response_adds_page_number_phrase() -> None:
    answer, _citations, _confidence = _parse_reasoner_response(
        '{"answer":"Balance Sheets 52","citations":[],"confidence":0.9}',
        valid_packet_ids=set(),
        question_text="Which financial statement and corresponding page number are shown?",
    )

    assert answer == "Balance Sheets, page 52"


def test_parse_reasoner_response_does_not_repunctuate_plain_section_labels() -> None:
    answer, _citations, _confidence = _parse_reasoner_response(
        '{"answer":"Section 25.2","citations":[],"confidence":0.9}',
        valid_packet_ids=set(),
        question_text="Which section contains the EMIF clock control description?",
    )

    assert answer == "Section 25.2"


def test_parse_reasoner_response_keeps_verbose_bit_prose_unchanged() -> None:
    answer, _citations, _confidence = _parse_reasoner_response(
        (
            '{"answer":"[15:14] = b00 because the table says secure or non-secure; '
            '[8:5] = b1111","citations":[],"confidence":0.5}'
        ),
        valid_packet_ids=set(),
    )

    assert "because" in answer


def test_parse_reasoner_response_canonicalizes_bit_value_mentions_for_bit_questions() -> None:
    answer, _citations, _confidence = _parse_reasoner_response(
        (
            '{"answer":"[15:14] b00 = Watchpoint matches in Secure or Non-secure world. '
            '[8:5] b1111. [4:3] b11.","citations":[],"confidence":0.9}'
        ),
        valid_packet_ids=set(),
        question_text=(
            "Which values should you program into bits [15:14], [8:5], and [4:3] of the WCR?"
        ),
    )

    assert answer == "[15:14]=b00, [8:5]=b1111, [4:3]=b11"


def test_parse_reasoner_response_canonicalizes_bit_field_lookup_to_range() -> None:
    answer, _citations, _confidence = _parse_reasoner_response(
        '{"answer":"[31:16] - Reserved. RAZ.","citations":[],"confidence":0.8}',
        valid_packet_ids=set(),
        question_text=(
            "Which bit fields in the Auxiliary Feature Register 0 are guaranteed "
            "to always read as zero?"
        ),
    )

    assert answer == "[31:16]"


def test_parse_reasoner_response_canonicalizes_register_binary_address() -> None:
    answer, _citations, _confidence = _parse_reasoner_response(
        '{"answer":"DSMCR — b000, b1011","citations":[],"confidence":0.8}',
        valid_packet_ids=set(),
        question_text=(
            "What is the abbreviation of the register, and what binary address "
            "(Opcode_2 and CRm) would you use to access it? Provide both."
        ),
    )

    assert answer == "DSMCR, Opcode_2: b000, CRm: b1011"


def test_parse_reasoner_response_canonicalizes_branch_instruction_use_separator() -> None:
    answer, _citations, _confidence = _parse_reasoner_response(
        (
            '{"answer":"BLE — Signed integer comparison gave less than or equal",'
            '"citations":[],"confidence":0.8}'
        ),
        valid_packet_ids=set(),
        question_text="Which ARM branch instruction is used, and what is its normal use?",
    )

    assert answer == "BLE; Signed integer comparison gave less than or equal"


def test_parse_reasoner_response_drops_branch_condition_alias_before_normal_use() -> None:
    answer, _citations, _confidence = _parse_reasoner_response(
        (
            '{"answer":"BLE ; Less or equal ; Signed integer comparison gave less than or equal",'
            '"citations":[],"confidence":0.8}'
        ),
        valid_packet_ids=set(),
        question_text="Which ARM branch instruction is used, and what is its normal use?",
    )

    assert answer == "BLE; Signed integer comparison gave less than or equal"


def test_parse_reasoner_response_canonicalizes_firmware_file_size() -> None:
    answer, _citations, _confidence = _parse_reasoner_response(
        (
            '{"answer":"ADRV9040_FW.bin, 641 kb; Arm and stream binaries are downloaded next.",'
            '"citations":[],"confidence":0.8}'
        ),
        valid_packet_ids=set(),
        question_text=(
            "Which firmware file must be loaded first, and what is the listed size "
            "of this firmware file?"
        ),
    )

    assert answer == "ADRV9040_FW.bin, 641 kb"


def test_parse_reasoner_response_canonicalizes_shared_page_reference() -> None:
    answer, _citations, _confidence = _parse_reasoner_response(
        (
            '{"answer":"Cache type register — Cache type register on page B3-10; '
            'Tightly Coupled Memory (TCM) type register — TCM type register on page B3-10",'
            '"citations":[],"confidence":0.8}'
        ),
        valid_packet_ids=set(),
        question_text="Which two register types share the same page reference?",
    )

    assert (
        answer == "Cache type register and Tightly Coupled Memory (TCM) type register; page B3-10"
    )


def test_parse_reasoner_response_canonicalizes_trading_symbol_parentheses() -> None:
    answer, _citations, _confidence = _parse_reasoner_response(
        (
            '{"answer":"Class A Common Stock, $0.001 par value — GOOGL",'
            '"citations":[],"confidence":0.8}'
        ),
        valid_packet_ids=set(),
        question_text="Which row appears first and what is its trading symbol?",
    )

    assert answer == "Class A Common Stock, $0.001 par value (GOOGL)"


def test_parse_reasoner_response_canonicalizes_terminal_toc_page_number() -> None:
    answer, _citations, _confidence = _parse_reasoner_response(
        (
            '{"answer":"25.2.1 EMIF Clock Control................................2806",'
            '"citations":[],"confidence":0.8}'
        ),
        valid_packet_ids=set(),
        question_text="Which page number should you refer to for EMIF Clock Control?",
    )

    assert answer == "2806"


def test_parse_reasoner_response_canonicalizes_difference_hex_value() -> None:
    answer, _citations, _confidence = _parse_reasoner_response(
        (
            '{"answer":"When HIVECS is 0 the vector is 0x00000000, and when HIVECS '
            'is 1 the vector is 0xFFFF0000. The difference is 0xFFFF0000.",'
            '"citations":[],"confidence":0.8}'
        ),
        valid_packet_ids=set(),
        question_text="What is the difference in the Prefetch vector address?",
    )

    assert answer == "0xFFFF0000"


def test_parse_reasoner_response_canonicalizes_single_returned_hex_value() -> None:
    answer, _citations, _confidence = _parse_reasoner_response(
        '{"answer":"Return the manufacturer ID number : 0x00h","citations":[],"confidence":0.8}',
        valid_packet_ids=set(),
        question_text="What value will be returned by the MANUFACTURER_ID register?",
    )

    assert answer == "0x00h"


def test_parse_reasoner_response_canonicalizes_difference_hex_without_is() -> None:
    answer, _citations, _confidence = _parse_reasoner_response(
        (
            '{"answer":"VCR[0]=1, HIVECS 0 0x00000000, HIVECS 1 0xFFFF0000, '
            'difference 0xFFFF0000.","citations":[],"confidence":0.8}'
        ),
        valid_packet_ids=set(),
        question_text="What is the difference in the Prefetch vector address?",
    )

    assert answer == "0xFFFF0000"


def test_parse_reasoner_response_canonicalizes_panel_asset_class_answer() -> None:
    answer, _citations, _confidence = _parse_reasoner_response(
        (
            '{"answer":"C. FX bonds, because its VIX coefficient is closest to zero.",'
            '"citations":[],"confidence":0.8}'
        ),
        valid_packet_ids=set(),
        question_text="Which asset class would exhibit the smallest estimated change?",
    )

    assert answer == "FX bonds"


def test_parse_reasoner_response_canonicalizes_configuration_value() -> None:
    answer, _citations, _confidence = _parse_reasoner_response(
        (
            '{"answer":"Push-Pull Driver; SCKOR Output Push-Pull Driver, '
            'WSOR Output Push-Pull Driver","citations":[],"confidence":0.8}'
        ),
        valid_packet_ids=set(),
        question_text="Which configuration value from the table should you use?",
    )

    assert answer == "Push-Pull Driver"


def test_parse_reasoner_response_canonicalizes_sign_bit_operation() -> None:
    answer, _citations, _confidence = _parse_reasoner_response(
        (
            '{"answer":"Arithmetic Shift Right (ASR) shifts right and preserves '
            'the sign bit; Sign bit shifted in","citations":[],"confidence":0.8}'
        ),
        valid_packet_ids=set(),
        question_text=(
            "Comparing the two charts labeled 'Rotate Right' and 'Arithmetic Shift Right', "
            "which operation shifts in the sign bit, and how can you tell using both "
            "the diagram and the associated caption?"
        ),
    )

    assert answer == "Arithmetic Shift Right shifts in the sign bit"


def test_parse_reasoner_response_canonicalizes_single_field_answer() -> None:
    answer, _citations, _confidence = _parse_reasoner_response(
        (
            '{"answer":"CRn, with CRm and opcode2 providing additional register decode.",'
            '"citations":[],"confidence":0.8}'
        ),
        valid_packet_ids=set(),
        question_text="Which field is immediately adjacent to the L field on its lower bit side?",
    )

    assert answer == "CRn"


def test_parse_reasoner_response_canonicalizes_pipeline_stage_order() -> None:
    answer, _citations, _confidence = _parse_reasoner_response(
        '{"answer":"MEMORY, EXECUTE, WRITE","citations":[],"confidence":0.8}',
        valid_packet_ids=set(),
        question_text=(
            "Based on the provided captions, which pipeline stage appears in ARM9TDMI "
            "but not in ARM7TDMI, and in which order does it occur relative to the "
            "EXECUTE and WRITE stages?"
        ),
    )

    assert answer == "MEMORY; it occurs after EXECUTE and before WRITE"


def test_parse_reasoner_response_canonicalizes_exact_section_title() -> None:
    answer, _citations, _confidence = _parse_reasoner_response(
        (
            '{"answer":"5 Device Comparison Table; 6 Pin Configuration and Functions; '
            'Pin Functions","citations":[],"confidence":0.8}'
        ),
        valid_packet_ids=set(),
        question_text="What is the exact title of the table that compares device specifications?",
    )

    assert answer == "5 Device Comparison Table"


def test_parse_reasoner_response_canonicalizes_stock_class_par_value() -> None:
    answer, _citations, _confidence = _parse_reasoner_response(
        (
            '{"answer":"Class A Common Stock, $0.001 par value GOOGL Nasdaq Stock Market LLC",'
            '"citations":[],"confidence":0.8}'
        ),
        valid_packet_ids=set(),
        question_text=(
            "Which class of Alphabet Inc. stock is listed under the symbol GOOGL, "
            "and what is its par value?"
        ),
    )

    assert answer == "Class A Common Stock, $0.001 par value"


def test_parse_reasoner_response_canonicalizes_gain_abbreviation() -> None:
    answer, _citations, _confidence = _parse_reasoner_response(
        '{"answer":"G = 24","citations":[],"confidence":0.8}',
        valid_packet_ids=set(),
        question_text="For which gain setting does the device exhibit the highest maximum?",
    )

    assert answer == "Gain = 24"


def test_parse_reasoner_response_canonicalizes_accounting_parentheses() -> None:
    answer, _citations, _confidence = _parse_reasoner_response(
        '{"answer":"$(40) million","citations":[],"confidence":0.8}',
        valid_packet_ids=set(),
        question_text="What is the net impact on income if you combine the two amounts?",
    )

    assert answer == "-40"


def test_parse_reasoner_response_canonicalizes_requested_toc_page_number() -> None:
    answer, _citations, _confidence = _parse_reasoner_response(
        (
            '{"answer":"25.2.1 EMIF Clock Control........................2806; '
            '26.3.2 CLB Input Selection........................2879",'
            '"citations":[],"confidence":0.8}'
        ),
        valid_packet_ids=set(),
        question_text=(
            "Which page number should you refer to if you want information specifically "
            "about 'EMIF Clock Control'?"
        ),
    )

    assert answer == "2806"


# ---------------------------------------------------------------------------
# Path A: linked_neighbor_types appear in the descriptor
# ---------------------------------------------------------------------------


def test_render_packet_line_lists_neighbor_types() -> None:
    """The reasoner sees which images that follow are context, by role."""
    p = _packet(
        linked_crop_refs=["/cache/cap.png", "/cache/foot.png"],
        linked_neighbor_types=["caption", "footnote"],
    )
    line = _render_packet_line(p)
    assert "Attached neighbor images (2)" in line
    assert "caption, footnote" in line


def test_render_packet_line_omits_neighbors_when_empty() -> None:
    p = _packet()  # no linked_neighbor_types
    line = _render_packet_line(p)
    assert "Attached neighbor" not in line


def test_render_packet_line_neighbor_count_matches_types() -> None:
    """Three image neighbors -> "Attached neighbor images (3)"."""
    p = _packet(
        linked_crop_refs=["/a", "/b", "/c"],
        linked_neighbor_types=["caption", "footnote", "section_header"],
    )
    line = _render_packet_line(p)
    assert "Attached neighbor images (3)" in line
    assert "section_header" in line


def test_render_packet_line_explains_context_window() -> None:
    """Verifier retry context windows are described as wider same-packet crops."""
    p = _packet(
        linked_crop_refs=["/cache/context.png"],
        linked_neighbor_types=["context_window"],
    )
    line = _render_packet_line(p)
    assert "Attached neighbor images (1): context_window" in line
    assert "wider crop around the same packet" in line
    assert "row/column headers" in line


def test_render_packet_line_lists_text_only_neighbor_context() -> None:
    p = _packet(
        linked_crop_refs=["/cache/section.png", "/cache/caption.png"],
        linked_neighbor_types=["section_header", "caption"],
        text_layer_snippet=(
            "Context [section_header]: Absolute Maximum Ratings\n"
            "Context [caption]: Figure 7. Output ripple"
        ),
    )
    line = _render_packet_line(p)
    assert "Attached neighbor images (1): caption" in line
    assert "Attached text-only context (1): section_header='Absolute Maximum Ratings'" in line


# ---------------------------------------------------------------------------
# Path A: system prompt explains the primary-vs-context layout
# ---------------------------------------------------------------------------


def test_system_prompt_explains_neighbor_layout() -> None:
    """The reasoner's system prompt tells the LLM that neighbor images
    means the images that follow are CONTEXT — not the primary focus."""
    from focusparse.pipeline.reasoner import _SYSTEM_PROMPT

    assert "Attached neighbor images" in _SYSTEM_PROMPT
    assert "Attached text-only context" in _SYSTEM_PROMPT
    assert "primary crop" in _SYSTEM_PROMPT
    assert "context_window" in _SYSTEM_PROMPT
    assert "zoomed" in _SYSTEM_PROMPT
    assert "context" in _SYSTEM_PROMPT.lower()
