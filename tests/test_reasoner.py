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
    assert "Attached neighbors (2)" in line
    assert "caption, footnote" in line


def test_render_packet_line_omits_neighbors_when_empty() -> None:
    p = _packet()  # no linked_neighbor_types
    line = _render_packet_line(p)
    assert "Attached neighbors" not in line


def test_render_packet_line_neighbor_count_matches_types() -> None:
    """Three neighbors → "Attached neighbors (3)"."""
    p = _packet(
        linked_crop_refs=["/a", "/b", "/c"],
        linked_neighbor_types=["caption", "footnote", "section_header"],
    )
    line = _render_packet_line(p)
    assert "Attached neighbors (3)" in line
    assert "section_header" in line


def test_render_packet_line_explains_context_window() -> None:
    """Verifier retry context windows are described as wider same-packet crops."""
    p = _packet(
        linked_crop_refs=["/cache/context.png"],
        linked_neighbor_types=["context_window"],
    )
    line = _render_packet_line(p)
    assert "Attached neighbors (1): context_window" in line
    assert "wider crop around the same packet" in line
    assert "row/column headers" in line


# ---------------------------------------------------------------------------
# Path A: system prompt explains the primary-vs-context layout
# ---------------------------------------------------------------------------


def test_system_prompt_explains_neighbor_layout() -> None:
    """The reasoner's system prompt tells the LLM that 'Attached neighbors'
    means the images that follow are CONTEXT — not the primary focus."""
    from focusparse.pipeline.reasoner import _SYSTEM_PROMPT

    assert "Attached neighbors" in _SYSTEM_PROMPT
    assert "primary crop" in _SYSTEM_PROMPT
    assert "context_window" in _SYSTEM_PROMPT
    assert "context" in _SYSTEM_PROMPT.lower()
