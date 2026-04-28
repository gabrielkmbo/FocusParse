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
from focusparse.tools.run_python import RunPythonInput, run_python

logger = logging.getLogger(__name__)


# Bbox area threshold for triggering auto-zoom (super-sampling). Regions
# whose normalized area is below this are candidates for LANCZOS 2× upsample
# via `run_python`. 0.005 ≈ a 70×70 px box on a 1000×1000 page — small enough
# that fine details (axis labels, footnotes) might be unreadable at native
# resolution.
_AUTOZOOM_AREA_THRESHOLD = 0.005

# LANCZOS 2× upsample code passed to the sandboxed `run_python`. The sandbox
# loads the input crop into `images[ref]`; we resize and `save_image()` the
# result. The sandbox returns a content-addressed ref we point the packet at.
_AUTOZOOM_CODE = """
from PIL import Image
ref = list(images.keys())[0]
img = images[ref]
w, h = img.size
out = img.resize((w * 2, h * 2), Image.Resampling.LANCZOS)
print("zoomed", img.size, "->", out.size)
save_image(out)
"""

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

# Map `plan.evidence_types` strings (planner vocabulary) to the region_type
# labels RT-DETRv2 emits. Planner uses coarse types (figure, table, text);
# detector uses fine labels (picture, table, section_header, etc.). This
# bridges the two vocabularies so the ranker can boost matches.
_EVIDENCE_TYPE_ALIASES: dict[str, frozenset[str]] = {
    "figure": frozenset({"picture", "image", "chart", "figure", "diagram"}),
    "chart": frozenset({"chart", "figure", "picture"}),
    "diagram": frozenset({"picture", "figure", "image", "diagram"}),
    "picture": frozenset({"picture", "image", "figure"}),
    "image": frozenset({"picture", "image", "figure"}),
    "table": frozenset({"table"}),
    "text": frozenset(
        {"text", "section_header", "section-header", "title", "list-item", "list_item"}
    ),
    "caption": frozenset({"caption"}),
    "footnote": frozenset({"footnote"}),
    "formula": frozenset({"formula"}),
    "header": frozenset({"page-header", "section_header", "section-header", "title"}),
    "footer": frozenset({"page-footer"}),
}

# Multiplicative boost applied to regions whose type matches any entry in
# `plan.evidence_types`. 1.5 was chosen so a figure region with score ~0.6
# can outrank a text region with score ~0.85 — which is the typical gap
# RT-DETRv2 shows between confident text and confident figures.
_EVIDENCE_TYPE_BOOST = 1.5

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
    auto_zoom: bool = False,
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
        auto_zoom: when True, regions whose bbox area is below
            `_AUTOZOOM_AREA_THRESHOLD` are super-sampled 2× via LANCZOS in
            the `run_python` sandbox. The packet's `local_crop_ref` then
            points to the upsampled PNG. Default off pending an A/B.

    Returns:
        An `EvidenceEvent` with one packet per inspected region. When
        every tool call fails for a region, a skeleton packet is still
        emitted with `provenance.tool="skeleton_inspector_fallback"` so
        the downstream stages always have something to work with.
    """
    del question  # reserved for LLM-driven inspector step 2

    max_crops = plan.max_crops or _DEFAULT_MAX_CROPS
    boosted_types = _expand_evidence_types(plan.evidence_types)
    ranked = sorted(
        regions.candidates,
        key=lambda r: -_rank_score(r, boosted_types),
    )[:max_crops]

    packets: list[EvidencePacket] = []
    for idx, region in enumerate(ranked):
        packet = await _inspect_one_region(
            idx,
            region,
            images_by_page=images_by_page,
            pdf_path=pdf_path,
            crop_cache_dir=crop_cache_dir,
            text_layer_cache_dir=text_layer_cache_dir,
            auto_zoom=auto_zoom,
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
    auto_zoom: bool = False,
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

    # --- 1b. Auto-zoom for tiny regions via run_python sandbox. ---
    if auto_zoom and crop_ref and crop_ref != page_thumbnail_ref:
        if _bbox_area(region.bbox_norm) < _AUTOZOOM_AREA_THRESHOLD:
            zoomed_ref = await _zoom_crop(
                crop_ref=crop_ref,
                cache_dir=crop_cache_dir,
                packet_id=packet_id,
            )
            if zoomed_ref is not None:
                crop_ref = zoomed_ref
                crop_signals.append("run_python:zoom2x")

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


# ---------------------------------------------------------------------------
# Ranking helpers
# ---------------------------------------------------------------------------


def _bbox_area(bbox: tuple[float, float, float, float]) -> float:
    """Return normalized [0,1]² area of a bbox. Negative-shaped bboxes → 0."""
    x0, y0, x1, y1 = bbox
    w = max(0.0, x1 - x0)
    h = max(0.0, y1 - y0)
    return w * h


async def _zoom_crop(
    *,
    crop_ref: str,
    cache_dir: Path | None,
    packet_id: str,
) -> str | None:
    """LANCZOS 2× upsample `crop_ref` via the run_python sandbox.

    Returns the path to the zoomed PNG (so the packet's `local_crop_ref`
    can swap to it) or None on any failure (silent — keep the original
    crop). Cache dir is the same content-addressed dir `inspect_region`
    writes to; the upsampled PNG goes there too keyed by sha256(bytes).
    """
    try:
        out = await run_python(
            RunPythonInput(code=_AUTOZOOM_CODE, image_refs=[crop_ref]),
            image_cache_dir=cache_dir,
            new_image_cache_dir=cache_dir,
        )
    except Exception as exc:  # noqa: BLE001 — sandbox is always best-effort
        logger.debug("run_python(zoom) failed for %s: %s", packet_id, exc)
        return None
    if out.exit_code != 0 or out.timed_out or not out.new_image_refs:
        logger.debug(
            "run_python(zoom) returned no new image for %s (exit=%d, timed_out=%s)",
            packet_id,
            out.exit_code,
            out.timed_out,
        )
        return None
    if cache_dir is None:
        return None
    return str(cache_dir / f"{out.new_image_refs[0]}.png")


def _expand_evidence_types(evidence_types: list[str] | None) -> frozenset[str]:
    """Turn planner-vocab `evidence_types` into a set of detector region_types.

    `evidence_types` uses coarse labels (figure, table, text); the layout
    endpoint emits fine labels (picture, table, section_header, caption).
    `_EVIDENCE_TYPE_ALIASES` maps the former to the latter — so asking for
    `["figure"]` boosts {picture, image, chart, figure, diagram}.

    Unknown planner labels are dropped silently rather than matching
    nothing; the alternative (literal match) would misfire whenever the
    planner uses a word the detector doesn't.
    """
    if not evidence_types:
        return frozenset()
    expanded: set[str] = set()
    for raw in evidence_types:
        key = (raw or "").strip().lower()
        if not key:
            continue
        aliases = _EVIDENCE_TYPE_ALIASES.get(key)
        if aliases is None:
            continue
        expanded |= aliases
    return frozenset(expanded)


def _rank_score(region: RegionCandidate, boosted_types: frozenset[str]) -> float:
    """Score used only for top-N selection; packet.confidence still carries
    the raw detector score.

    Applies a fixed multiplicative boost when a region's type matches any
    requested evidence type. This lets a confident figure (score 0.6)
    outrank a confident text region (score 0.85) when the planner asked
    for figures — the core smoke-test observation this helper exists for.
    """
    base = float(region.score)
    if not boosted_types:
        return base
    rtype = (region.region_type or "").lower()
    if rtype and rtype in boosted_types:
        return base * _EVIDENCE_TYPE_BOOST
    return base
