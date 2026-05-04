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
from focusparse.pipeline.reasoner import _collect_packet_images, _render_packet_line


def _packet(
    *,
    packet_id: str = "pkt_000",
    page: int = 3,
    bbox: tuple[float, float, float, float] = (0.1, 0.2, 0.5, 0.6),
    local_crop_ref: str = "/cache/crops/abc.png",
    page_thumbnail_ref: str = "/cache/pages/p3.png",
    multi_scale: list[CropRef] | None = None,
) -> EvidencePacket:
    return EvidencePacket(
        packet_id=packet_id,
        page=page,
        bbox_norm=bbox,
        page_thumbnail_ref=page_thumbnail_ref,
        local_crop_ref=local_crop_ref,
        multi_scale_crops=multi_scale or [],
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
    assert "2 image scales" in line
    assert "tight + context" in line


def test_render_packet_line_single_scale_does_not_annotate() -> None:
    """Multi-scale list of length 1 is degenerate (just tight); no annotation."""
    p = _packet(
        multi_scale=[
            CropRef(ref="/a.png", bbox_norm=(0, 0, 1, 1), scale="tight"),
        ]
    )
    line = _render_packet_line(p)
    assert "image scales" not in line


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
