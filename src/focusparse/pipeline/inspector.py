"""INSPECT stage — smart-deterministic tool dispatcher.

Sub-phase 2g step 1 replaces the skeleton (raw-page packets) with real
tool-driven evidence. For each `RegionCandidate` from the localizer, the
inspector:

  1. Ranks regions by `score` descending and caps at `plan.max_crops`.
  2. Calls `inspect_region(mode='image')` to produce a cropped PNG on
     disk — this is always useful because the VLM reads the crop
     directly during `answer`.
  3. For text-bearing regions (region_type in TEXT_REGION_TYPES) AND
     when a PDF is available, calls `get_text_layer` with the bbox to
     pull native PDF text. This is deterministic and free.
  4. When native text is empty (image-only PDF) OR no PDF was supplied,
     falls back to `inspect_region(mode='element')` with Tesseract.
  5. For visual regions (picture / chart) we skip OCR entirely — the
     VLM is better at reading those than Tesseract ever will be.

The result is a list of `EvidencePacket`s with real `local_crop_ref`,
`text_layer_snippet`, and `ocr_snippet` fields populated. The reasoner
finally sees focused evidence instead of raw page images.

Step 2 (not yet shipped) adds an LLM-driven ReAct loop that decides
WHICH regions to inspect, using `run_python` for numeric zoom and
revisiting when confidence is low. The deterministic path is the
floor we evaluate against.
"""

from __future__ import annotations

import logging
from pathlib import Path

from focusparse.evidence.packet import EvidencePacket, PacketProvenance
from focusparse.pipeline.events import (
    EvidenceEvent,
    PlanEvent,
    QuestionEvent,
    RegionCandidate,
    RegionsEvent,
)
from focusparse.tools.get_text_layer import GetTextLayerInput, get_text_layer
from focusparse.tools.inspect_region import InspectRegionInput, inspect_region

logger = logging.getLogger(__name__)

# Region types where native text extraction + OCR make sense. The layout
# endpoint's RT-DETRv2 emits these labels plus picture/chart etc. where we
# skip OCR. The set is intentionally permissive — unknown labels get OCR
# too, so a new label never silently becomes invisible.
_TEXT_REGION_TYPES = frozenset(
    {
        "text",
        "table",
        "section_header",
        "section-header",
        "title",
        "list-item",
        "list_item",
        "caption",
        "footnote",
        "formula",
        "page-header",
        "page-footer",
    }
)

# Visual region types where Tesseract OCR adds nothing (the VLM reads the
# crop directly). Still get a crop; just no `element` mode pass.
_VISUAL_REGION_TYPES = frozenset({"picture", "image", "chart", "figure"})

_DEFAULT_MAX_CROPS = 8
_MIN_TEXT_LAYER_CHARS = 4  # anything shorter is "basically empty"


async def inspect_regions(
    question: QuestionEvent,
    plan: PlanEvent,
    regions: RegionsEvent,
    *,
    images_by_page: dict[int, Path],
    pdf_path: Path | None = None,
    crop_cache_dir: Path | None = None,
    text_layer_cache_dir: Path | None = None,
) -> EvidenceEvent:
    """Produce real `EvidencePacket`s via the tool belt.

    Args:
        question / plan: upstream events. `plan.max_crops` caps how many
            regions we inspect.
        regions: `RegionCandidate`s from the localizer.
        images_by_page: 1-indexed page -> PNG path. Used as a fallback
            `page_thumbnail_ref` when cropping fails.
        pdf_path: source PDF. When supplied, text-bearing regions get a
            deterministic `text_layer_snippet` via `get_text_layer`.
            When None, we fall back to Tesseract on the crop.
        crop_cache_dir: where cropped PNGs go. Passed through to
            `inspect_region`. When None, a `cache/crops/` dir is created
            under CWD (test-only convenience).
        text_layer_cache_dir: where native-text extractions are memoized.

    Returns:
        An `EvidenceEvent` with one packet per inspected region. When
        every tool call fails for a region, a skeleton packet is still
        emitted with `provenance.tool="skeleton_inspector_fallback"` so
        the downstream stages always have something to work with.
    """
    del question  # reserved for LLM-driven inspector step 2

    max_crops = plan.max_crops or _DEFAULT_MAX_CROPS
    ranked = sorted(regions.candidates, key=lambda r: -r.score)[:max_crops]

    packets: list[EvidencePacket] = []
    for idx, region in enumerate(ranked):
        packet = await _inspect_one_region(
            idx,
            region,
            images_by_page=images_by_page,
            pdf_path=pdf_path,
            crop_cache_dir=crop_cache_dir,
            text_layer_cache_dir=text_layer_cache_dir,
        )
        packets.append(packet)
    return EvidenceEvent(packets=packets)


# ---------------------------------------------------------------------------
# Per-region tool dispatch
# ---------------------------------------------------------------------------


async def _inspect_one_region(
    idx: int,
    region: RegionCandidate,
    *,
    images_by_page: dict[int, Path],
    pdf_path: Path | None,
    crop_cache_dir: Path | None,
    text_layer_cache_dir: Path | None,
) -> EvidencePacket:
    """Run the tool chain for one region and bundle the outputs into a packet."""
    page_image = images_by_page.get(region.page)
    page_thumbnail_ref = str(page_image) if page_image is not None else ""

    packet_id = f"pkt_{idx:03d}"
    region_type = (region.region_type or "").lower() or None
    is_visual = region_type in _VISUAL_REGION_TYPES
    is_texty = region_type in _TEXT_REGION_TYPES or region_type is None

    # --- 1. Always crop (image mode). The VLM reads this at `answer`. ---
    crop_ref = page_thumbnail_ref
    crop_signals: list[str] = []
    if pdf_path is not None:
        try:
            crop_out = await inspect_region(
                InspectRegionInput(
                    doc_path=str(pdf_path),
                    page=region.page,
                    bbox_norm=region.bbox_norm,
                    mode="image",
                    expansion="default",
                ),
                cache_dir=crop_cache_dir,
            )
            crop_ref = crop_out.crop_ref
            crop_signals.append("inspect_region:image")
        except (FileNotFoundError, ValueError) as exc:
            # Missing PDF / invalid bbox → keep the page image as fallback.
            logger.debug("inspect_region(image) failed for %s: %s", packet_id, exc)

    # --- 2. Text extraction — prefer native PDF, fall back to OCR. ---
    text_layer_snippet: str | None = None
    ocr_snippet: str | None = None
    confidence = float(region.score)

    if is_texty and pdf_path is not None:
        try:
            text_out = await get_text_layer(
                GetTextLayerInput(
                    doc_path=str(pdf_path),
                    page=region.page,
                    bbox_norm=region.bbox_norm,
                ),
                cache_dir=text_layer_cache_dir,
            )
            if text_out.text and len(text_out.text.strip()) >= _MIN_TEXT_LAYER_CHARS:
                text_layer_snippet = text_out.text
                crop_signals.append(f"get_text_layer:{text_out.source}")
        except (FileNotFoundError, ValueError) as exc:
            logger.debug("get_text_layer failed for %s: %s", packet_id, exc)

    # OCR the crop when:
    #  * region is text-bearing (or unknown), AND
    #  * we didn't get usable native text, AND
    #  * we have a PDF (inspect_region needs the source PDF)
    need_ocr = is_texty and text_layer_snippet is None and pdf_path is not None and not is_visual
    if need_ocr:
        try:
            element_out = await inspect_region(
                InspectRegionInput(
                    doc_path=str(pdf_path),
                    page=region.page,
                    bbox_norm=region.bbox_norm,
                    mode="element",
                    expansion="default",
                ),
                cache_dir=crop_cache_dir,
            )
            if element_out.ocr_text:
                ocr_snippet = element_out.ocr_text
                crop_signals.append("inspect_region:element")
                # When OCR confidence is meaningful, fold it into the packet
                # confidence so downstream ranking respects uncertain reads.
                if element_out.confidence > 0:
                    confidence = min(confidence, element_out.confidence)
        except (FileNotFoundError, ValueError) as exc:
            logger.debug("inspect_region(element) failed for %s: %s", packet_id, exc)

    commit_level = "image" if is_visual else "element"
    provenance_tool = "deterministic_inspector" if crop_signals else "skeleton_inspector_fallback"
    return EvidencePacket(
        packet_id=packet_id,
        page=region.page,
        bbox_norm=region.bbox_norm,
        region_type=region.region_type,
        page_thumbnail_ref=page_thumbnail_ref,
        local_crop_ref=crop_ref,
        ocr_snippet=ocr_snippet,
        text_layer_snippet=text_layer_snippet,
        commit_level=commit_level,
        provenance=PacketProvenance(
            tool=provenance_tool,
            mode=("visual" if is_visual else "text+image"),
            args_hash="|".join(crop_signals),
        ),
        confidence=confidence,
    )
