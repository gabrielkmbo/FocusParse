"""EvidencePacket — the only thing the reasoner ever sees.

Invariant: every reasoner call receives `list[EvidencePacket]` assembled by the
packager step. The reasoner never sees raw pages. This is how we avoid the
"found the plot but missed the footnote" failure mode that the parser-bench
slide deck flags repeatedly.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PacketProvenance(BaseModel):
    """Which tool produced this packet + with what args."""

    tool: str
    mode: str | None = None
    args_hash: str  # sha256 of the tool input for cache lookup
    tokens_used: int = 0
    latency_ms: int = 0


class CropRef(BaseModel):
    """One crop scale of an evidence region (Phase 6 #6, sprint Phase 2).

    Sprint plan 2026-05-04 introduces this as the typed unit for
    `EvidencePacket.multi_scale_crops`. Element 0 is always the tight
    crop (mirrors `local_crop_ref` for back-compat); subsequent elements
    are wider contexts that carry the same target bbox at progressively
    larger pads (default: tight + 30% pad).
    """

    ref: str  # absolute path to the cached PNG
    bbox_norm: tuple[float, float, float, float]
    scale: Literal["tight", "context"] = "tight"


class EvidencePacket(BaseModel):
    """A compact bundle of evidence around a single region of interest.

    Shipped from the packager to the reasoner. Always includes a page thumbnail
    with the focus bbox highlighted, so the reasoner retains global context.
    """

    packet_id: str  # stable id, used as a citation key
    page: int  # 1-indexed, matches parser-bench BBox.page
    bbox_norm: tuple[float, float, float, float]  # normalized [x0, y0, x1, y1]
    region_type: str | None = None  # parser_bench RegionType value

    # Image assets (content-addressed paths in cache/)
    page_thumbnail_ref: str  # page with bbox highlighted, low DPI
    local_crop_ref: str  # tight crop at working DPI
    context_crop_ref: str | None = (
        None  # legacy single context crop; superseded by multi_scale_crops
    )
    multi_scale_crops: list[CropRef] = Field(
        default_factory=list,
        description=(
            "Tight + context crops for the same target region. Element 0 is "
            "the tight crop (mirrors local_crop_ref); elements 1+ are wider "
            "contexts. Empty for legacy single-scale packets — the reasoner "
            "should iterate this list when non-empty, otherwise fall back "
            "to local_crop_ref."
        ),
    )
    linked_crop_refs: list[str] = Field(default_factory=list)  # legend, footnote, caption, header

    # Text
    ocr_snippet: str | None = None
    text_layer_snippet: str | None = None  # deterministic PDF text for this bbox

    # Structure
    linked_neighbor_types: list[str] = Field(default_factory=list)  # e.g. ["legend", "caption"]
    evidence_edges: list[str] = Field(default_factory=list)  # EdgeType values

    # Meta
    dpi: int = 300
    commit_level: Literal["image", "element", "region"] = "element"
    provenance: PacketProvenance
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
