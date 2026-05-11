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
  4. When native text is empty (image-only PDF) and a source PDF is available,
     falls back to `inspect_region(mode='element')` with Tesseract.
  5. For visual regions (picture / chart) we still keep the crop as the
     primary artifact, but also run best-effort OCR so embedded chart labels,
     captions, and callouts can reach downstream text-only checks.

The result is a list of `EvidencePacket`s with real `local_crop_ref`,
`text_layer_snippet`, and `ocr_snippet` fields populated. The reasoner
finally sees focused evidence instead of raw page images.

Step 2 (not yet shipped) adds an LLM-driven ReAct loop that decides
WHICH regions to inspect, using `run_python` for numeric zoom and
revisiting when confidence is low. The deterministic path is the
floor we evaluate against.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

from focusparse.evidence.packet import CropRef, EvidencePacket, PacketProvenance
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
_AUTOZOOM_MAX_DIM = 2048

# LANCZOS 2× upsample code passed to the sandboxed `run_python`. The sandbox
# loads the input crop into `images[ref]`; we resize and `save_image()` the
# result. Larger retry crops are capped so visual readability repairs cannot
# hand the reasoner oversized images. The sandbox returns a content-addressed
# ref we point the packet at.
_AUTOZOOM_CODE = f"""
from PIL import Image
ref = list(images.keys())[0]
img = images[ref]
w, h = img.size
target_w, target_h = w * 2, h * 2
max_dim = {_AUTOZOOM_MAX_DIM}
if max(target_w, target_h) > max_dim:
    scale = max_dim / max(target_w, target_h)
    target_w = max(1, int(round(target_w * scale)))
    target_h = max(1, int(round(target_h * scale)))
out = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
print("zoomed", img.size, "->", out.size)
save_image(out)
"""

# Region types where native text extraction + OCR make sense. The layout
# endpoint's RT-DETRv2 emits these labels plus picture/chart etc. The set is
# intentionally permissive — unknown labels get OCR too, so a new label never
# silently becomes invisible.
_TEXT_REGION_TYPES = frozenset(
    {
        "axis-label",
        "axis_label",
        "text",
        "table",
        "section_header",
        "section-header",
        "title",
        "list-item",
        "list_item",
        "caption",
        "checkbox-selected",
        "checkbox_selected",
        "checkbox-unselected",
        "checkbox_unselected",
        "code",
        "document index",
        "document_index",
        "footnote",
        "formula",
        "form",
        "key-value region",
        "key_value_region",
        "legend",
        "page-header",
        "page-footer",
        "tick-label",
        "tick_label",
    }
)

# Visual region types whose crop remains the primary evidence. They also get
# a best-effort `element` OCR pass so text embedded in figures/charts is not
# invisible to the verifier or trace diagnostics.
_VISUAL_REGION_TYPES = frozenset(
    {
        "bar_chart",
        "candlestick",
        "chart",
        "curve",
        "diagram",
        "figure",
        "image",
        "line_chart",
        "picture",
        "plot",
    }
)

# Map `plan.evidence_types` strings (planner vocabulary) to the region_type
# labels RT-DETRv2 emits. Planner uses coarse types (figure, table, text);
# detector uses fine labels (picture, table, section_header, etc.). This
# bridges the two vocabularies so the ranker can boost matches.
_EVIDENCE_TYPE_ALIASES: dict[str, frozenset[str]] = {
    "axis": frozenset({"axis-label", "axis_label", "tick-label", "tick_label"}),
    "axis_label": frozenset({"axis-label", "axis_label", "tick-label", "tick_label"}),
    "figure": frozenset({"picture", "image", "chart", "figure", "diagram", "plot", "curve"}),
    "chart": frozenset(
        {
            "bar_chart",
            "candlestick",
            "chart",
            "curve",
            "figure",
            "line_chart",
            "picture",
            "plot",
        }
    ),
    "diagram": frozenset({"picture", "figure", "image", "diagram"}),
    "picture": frozenset({"picture", "image", "figure"}),
    "image": frozenset({"picture", "image", "figure"}),
    "table": frozenset({"table"}),
    "text": frozenset(
        {
            "checkbox-selected",
            "checkbox_selected",
            "code",
            "document index",
            "document_index",
            "form",
            "key-value region",
            "key_value_region",
            "list-item",
            "list_item",
            "section_header",
            "section-header",
            "text",
            "title",
        }
    ),
    "caption": frozenset({"caption"}),
    "footnote": frozenset({"footnote"}),
    "formula": frozenset({"formula"}),
    "header": frozenset({"page-header", "section_header", "section-header", "title"}),
    "legend": frozenset({"legend"}),
    "footer": frozenset({"page-footer"}),
}

# Multiplicative boost applied to regions whose type matches any entry in
# `plan.evidence_types`. 1.5 was chosen so a figure region with score ~0.6
# can outrank a text region with score ~0.85 — which is the typical gap
# RT-DETRv2 shows between confident text and confident figures.
_EVIDENCE_TYPE_BOOST = 1.5

_DEFAULT_MAX_CROPS = 8
_MIN_TEXT_LAYER_CHARS = 4  # anything shorter is "basically empty"
_IMAGE_FALLBACK_EXPANSION = 0.02
_CHART_CONTEXT_PAD = 0.12
_VISUAL_CONTEXT_PAD = 0.16
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_CHART_SCALE_RE = re.compile(
    r"\b(?P<label>[A-Z][A-Z0-9_ ]{0,24}?)\s*"
    r"(?:\(|=|:)?\s*"
    r"(?P<value>[+-]?\d+(?:\.\d+)?)\s*"
    r"(?P<unit>mV|V|uV|µV|nV|us|µs|ms|s|ns)\s*/\s*div\b",
    re.IGNORECASE,
)
_QUESTION_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "based",
        "be",
        "between",
        "by",
        "considering",
        "during",
        "estimate",
        "for",
        "from",
        "give",
        "in",
        "is",
        "it",
        "nearest",
        "of",
        "on",
        "only",
        "reached",
        "the",
        "this",
        "to",
        "using",
        "value",
        "what",
        "when",
        "with",
    }
)

# Question families where chart_to_table CSV extraction is worth the cost.
# Other question types use inspect_region (visual reading) only.
#
# Initially {axis_value_interpolation, candlestick_ohlc_extraction,
# curve_axis_reading}. Expanded 2026-05-11 (harness-growth Phase 1) to cover
# the rest of the planner's chart-bearing families because:
#
#   1. The gate is `chart_extraction_active AND _region_is_chart(region)`.
#      Non-chart regions cannot trigger chart_to_table even if the family is
#      listed, so expansion is safe for non-chart questions.
#   2. chart_to_table failures collapse to an empty CSV with the visual crop
#      preserved, so a low-quality chart never poisons the packet.
#   3. Finance is the weak domain in the headline (~32-43% vs ~50% datasheets)
#      and most finance failures are chart-table cross-references — exactly
#      what chart_to_table was built for.
_CHART_QUESTION_FAMILIES = frozenset(
    {
        "axis_value_interpolation",
        "candlestick_ohlc_extraction",
        "curve_axis_reading",
        # Added 2026-05-11 (Phase 1 of harness-growth-sprint):
        "chart_table_cross_ref",
        "legend_series_binding",
        "multi_chart_comparison",
        "chart_caption_fusion",
        "chart_footnote_fusion",
        "dual_axis_disambiguation",
    }
)
_CHART_FIGURE_CLASSES = frozenset({"bar_chart", "line_chart", "candlestick"})

# Sprint 2026-05-05 (Phase B2): question families where auto-zoom (run_python
# LANCZOS supersample) is worth firing even on regions LARGER than
# `_AUTOZOOM_AREA_THRESHOLD`. These all need fine-detail visual reading where
# 2× supersample buys real signal regardless of crop size.
_FINE_DETAIL_QUESTION_FAMILIES = frozenset(
    {
        "axis_value_interpolation",
        "confusable_label",
        "direct_label_reading",
        "legend_series_binding",
        "min_typ_max_disambiguation",
        "package_mechanical_reading",
        "timing_diagram_reading",
    }
)

# Families where the target visual region is often correct but the answer
# depends on labels, markers, or sibling panels just outside the tight bbox.
_VISUAL_CONTEXT_QUESTION_FAMILIES = frozenset(
    {
        "chart_caption_fusion",
        "curve_axis_reading",
        "direct_label_reading",
        "legend_series_binding",
        "multi_chart_comparison",
        "timing_diagram_reading",
    }
)
_BROAD_VISUAL_CONTEXT_QUESTION_FAMILIES = frozenset(
    {
        "legend_series_binding",
        "multi_chart_comparison",
    }
)
_BROAD_VISUAL_CONTEXT_MAX_PACKETS = 2
_BROAD_VISUAL_CONTEXT_MIN_RELEVANCE = 0.65


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
    multi_scale: bool = False,
    chart_to_table_enabled: bool = False,
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
    max_crops = plan.max_crops or _DEFAULT_MAX_CROPS
    boosted_types = _expand_evidence_types(plan.evidence_types)
    evidence_keys = {(raw or "").strip().lower() for raw in (plan.evidence_types or [])}
    wants_chart = (
        plan.question_family or ""
    ) in _CHART_QUESTION_FAMILIES or "chart" in evidence_keys
    ranked_all = sorted(
        regions.candidates,
        key=lambda r: -_rank_score(r, boosted_types, wants_chart=wants_chart),
    )
    ranked = _select_regions_for_inspection(
        ranked_all,
        max_crops=max_crops,
        plan=plan,
    )

    chart_extraction_active = chart_to_table_enabled and wants_chart

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
            multi_scale=multi_scale,
            chart_extraction_active=chart_extraction_active,
            chart_context_active=wants_chart,
            question_family=plan.question_family,
            question_text=question.question,
        )
        packets.append(packet)
    if wants_chart:
        packets.sort(key=lambda p: -_packet_question_overlap(question.question, p))
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
    multi_scale: bool = False,
    chart_extraction_active: bool = False,
    chart_context_active: bool = False,
    question_family: str | None = None,
    question_text: str | None = None,
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
    multi_scale_crops: list[CropRef] = []
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
    elif page_image is not None:
        try:
            crop_ref = _crop_page_image(
                page_image,
                region.bbox_norm,
                cache_dir=crop_cache_dir,
                expansion=_IMAGE_FALLBACK_EXPANSION,
            )
            crop_signals.append("page_image_crop:image")
        except (FileNotFoundError, OSError, ValueError) as exc:
            # Missing/corrupt staged image → preserve the historical skeleton fallback.
            logger.debug("page-image crop failed for %s: %s", packet_id, exc)

    # --- 1a (Phase 6 #6 / sprint Phase 2). Multi-scale: also render a wider
    # context crop (~30% pad) so the reasoner sees both tight + context for
    # the same region. Skipped only when the tight crop fell back to the page
    # thumbnail; PDF-backed and page-image-backed tight crops can both widen.
    if multi_scale and crop_ref and crop_ref != page_thumbnail_ref:
        context_bbox = _expand_bbox(region.bbox_norm, pad=0.30)
        if pdf_path is not None:
            try:
                ctx_out = await inspect_region(
                    InspectRegionInput(
                        doc_path=str(pdf_path),
                        page=region.page,
                        bbox_norm=context_bbox,
                        mode="image",
                        expansion="none",  # already padded; don't double-expand
                    ),
                    cache_dir=crop_cache_dir,
                )
                multi_scale_crops = [
                    CropRef(ref=crop_ref, bbox_norm=region.bbox_norm, scale="tight"),
                    CropRef(ref=ctx_out.crop_ref, bbox_norm=context_bbox, scale="context"),
                ]
                crop_signals.append("inspect_region:context")
            except (FileNotFoundError, ValueError) as exc:
                logger.debug("inspect_region(context) failed for %s: %s", packet_id, exc)
        elif page_image is not None:
            try:
                ctx_ref = _crop_page_image(
                    page_image,
                    context_bbox,
                    cache_dir=crop_cache_dir,
                    expansion=0.0,
                )
                multi_scale_crops = [
                    CropRef(ref=crop_ref, bbox_norm=region.bbox_norm, scale="tight"),
                    CropRef(ref=ctx_ref, bbox_norm=context_bbox, scale="context"),
                ]
                crop_signals.append("page_image_crop:context")
            except (FileNotFoundError, OSError, ValueError) as exc:
                logger.debug("page-image context crop failed for %s: %s", packet_id, exc)

    # Chart-reading failures often cite the right tight crop but need the
    # surrounding axes/curve context for numeric interpolation. Add a modest
    # wider crop only when chart extraction is active; the general multi-scale
    # flag remains the larger 30% context experiment.
    if (
        not multi_scale_crops
        and chart_context_active
        and is_visual
        and crop_ref
        and crop_ref != page_thumbnail_ref
        and _region_is_chart(region)
        and _allow_proactive_context_crop(question_family, region, packet_index=idx)
    ):
        context_bbox = _expand_bbox(region.bbox_norm, pad=_CHART_CONTEXT_PAD)
        if pdf_path is not None:
            try:
                ctx_out = await inspect_region(
                    InspectRegionInput(
                        doc_path=str(pdf_path),
                        page=region.page,
                        bbox_norm=context_bbox,
                        mode="image",
                        expansion="none",
                    ),
                    cache_dir=crop_cache_dir,
                )
                multi_scale_crops = [
                    CropRef(ref=crop_ref, bbox_norm=region.bbox_norm, scale="tight"),
                    CropRef(ref=ctx_out.crop_ref, bbox_norm=context_bbox, scale="chart_context"),
                ]
                crop_signals.append("inspect_region:chart_context")
            except (FileNotFoundError, ValueError) as exc:
                logger.debug("inspect_region(chart_context) failed for %s: %s", packet_id, exc)
        elif page_image is not None:
            try:
                ctx_ref = _crop_page_image(
                    page_image,
                    context_bbox,
                    cache_dir=crop_cache_dir,
                    expansion=0.0,
                )
                multi_scale_crops = [
                    CropRef(ref=crop_ref, bbox_norm=region.bbox_norm, scale="tight"),
                    CropRef(ref=ctx_ref, bbox_norm=context_bbox, scale="chart_context"),
                ]
                crop_signals.append("page_image_crop:chart_context")
            except (FileNotFoundError, OSError, ValueError) as exc:
                logger.debug("page-image chart context crop failed for %s: %s", packet_id, exc)

    # Timing diagrams, label-binding charts, and multi-panel visual questions
    # often localize the right object but need a little surrounding context for
    # markers, axis labels, symbol definitions, or sibling panels. Add a modest
    # context crop for those families without enabling broad multi_scale for
    # every packet in the headline path.
    if (
        not multi_scale_crops
        and _needs_visual_context_crop(question_family)
        and is_visual
        and crop_ref
        and crop_ref != page_thumbnail_ref
        and _allow_proactive_context_crop(question_family, region, packet_index=idx)
    ):
        context_bbox = _expand_bbox(region.bbox_norm, pad=_VISUAL_CONTEXT_PAD)
        if pdf_path is not None:
            try:
                ctx_out = await inspect_region(
                    InspectRegionInput(
                        doc_path=str(pdf_path),
                        page=region.page,
                        bbox_norm=context_bbox,
                        mode="image",
                        expansion="none",
                    ),
                    cache_dir=crop_cache_dir,
                )
                multi_scale_crops = [
                    CropRef(ref=crop_ref, bbox_norm=region.bbox_norm, scale="tight"),
                    CropRef(ref=ctx_out.crop_ref, bbox_norm=context_bbox, scale="context"),
                ]
                crop_signals.append("inspect_region:visual_context")
            except (FileNotFoundError, ValueError) as exc:
                logger.debug("inspect_region(visual_context) failed for %s: %s", packet_id, exc)
        elif page_image is not None:
            try:
                ctx_ref = _crop_page_image(
                    page_image,
                    context_bbox,
                    cache_dir=crop_cache_dir,
                    expansion=0.0,
                )
                multi_scale_crops = [
                    CropRef(ref=crop_ref, bbox_norm=region.bbox_norm, scale="tight"),
                    CropRef(ref=ctx_ref, bbox_norm=context_bbox, scale="context"),
                ]
                crop_signals.append("page_image_crop:visual_context")
            except (FileNotFoundError, OSError, ValueError) as exc:
                logger.debug("page-image visual context crop failed for %s: %s", packet_id, exc)

    # --- 1b. Auto-zoom via run_python sandbox.
    #
    # 2026-05-05 (Phase B2) reshapes this from "replace local_crop_ref with
    # the upsampled crop on tiny regions" to "ADD a CropRef(scale='zoomed')
    # to multi_scale_crops" — the reasoner sees BOTH original and zoomed.
    # Activation is now query-aware: tiny bbox OR fine-detail question.
    if auto_zoom and crop_ref and crop_ref != page_thumbnail_ref:
        is_tiny = _bbox_area(region.bbox_norm) < _AUTOZOOM_AREA_THRESHOLD
        is_fine_detail_q = (question_family or "") in _FINE_DETAIL_QUESTION_FAMILIES
        if is_tiny or is_fine_detail_q:
            zoomed_ref = await _zoom_crop(
                crop_ref=crop_ref,
                cache_dir=crop_cache_dir,
                packet_id=packet_id,
            )
            if zoomed_ref is not None:
                # Record the zoomed crop in multi_scale_crops alongside the
                # tight (and optional context) crops. Keep `crop_ref` (and
                # therefore `local_crop_ref`) unchanged so legacy reasoner
                # callers that read only the tight crop still work.
                if not multi_scale_crops:
                    # Seed with tight crop so element 0 is always present.
                    multi_scale_crops = [
                        CropRef(ref=crop_ref, bbox_norm=region.bbox_norm, scale="tight"),
                    ]
                multi_scale_crops.append(
                    CropRef(ref=zoomed_ref, bbox_norm=region.bbox_norm, scale="zoomed")
                )
                crop_signals.append(
                    "run_python:zoom2x" + ("" if is_tiny else f"@{question_family}")
                )

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
    #  * region is text-bearing/unknown OR visual, AND
    #  * we didn't get usable native text, AND
    #  * either a PDF-backed crop or a page-image fallback crop exists.
    #
    # For visual packets, OCR is advisory: the crop remains the primary
    # evidence (`commit_level="image"`), but OCR can expose embedded labels,
    # axis ticks, captions, or callouts to text-only verifier summaries.
    need_ocr = (
        (is_texty or is_visual)
        and text_layer_snippet is None
        and crop_ref
        and crop_ref != page_thumbnail_ref
    )
    if need_ocr:
        if pdf_path is not None:
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
                    # When OCR confidence is meaningful for text packets, fold it
                    # into packet confidence so downstream ranking respects
                    # uncertain reads. For visual packets, OCR is auxiliary and
                    # should not down-rank the visual crop itself.
                    if element_out.confidence > 0 and not is_visual:
                        confidence = min(confidence, element_out.confidence)
            except (FileNotFoundError, ValueError) as exc:
                logger.debug("inspect_region(element) failed for %s: %s", packet_id, exc)
            # If element-mode OCR returns empty (or fails), fall back to OCR on
            # the already-materialized crop. This recovers text labels from
            # page-image fallback crops and from element-mode misses without
            # forcing the packet into a text-first commit level.
            if ocr_snippet is None and crop_ref and crop_ref != page_thumbnail_ref:
                fallback_ocr, fallback_confidence = _ocr_existing_crop(Path(crop_ref))
                if fallback_ocr:
                    ocr_snippet = fallback_ocr
                    crop_signals.append("inspect_region:crop_fallback_ocr")
                    if fallback_confidence > 0 and not is_visual:
                        confidence = min(confidence, fallback_confidence)
        else:
            fallback_ocr, fallback_confidence = _ocr_existing_crop(Path(crop_ref))
            if fallback_ocr:
                ocr_snippet = fallback_ocr
                crop_signals.append("page_image_crop:ocr")
                if fallback_confidence > 0 and not is_visual:
                    confidence = min(confidence, fallback_confidence)

    # --- 3. (Phase 6 #7 / sprint Phase 3) chart_to_table extraction.
    # Fires only when the question is a chart-reading family AND the region
    # is a chart-class figure AND the tight crop succeeded. Best-effort:
    # failures collapse confidence; the reasoner still has the raw crop.
    chart_csv: str | None = None
    chart_extraction_confidence: float | None = None
    chart_packet_note: str | None = None
    if (
        chart_extraction_active
        and is_visual
        and crop_ref
        and crop_ref != page_thumbnail_ref
        and _region_is_chart(region)
    ):
        figure_class = _figure_class(region) or "chart"
        crop_signals.append("chart_to_table:attempt")
        try:
            from focusparse.tools.chart_to_table import (
                ChartToTableInput,
                chart_to_table,
            )

            chart_out = await chart_to_table(
                ChartToTableInput(crop_ref=crop_ref),
                crop_cache_dir=crop_cache_dir,
            )
            if chart_out.table_csv:
                chart_csv = chart_out.table_csv
                chart_extraction_confidence = chart_out.confidence
                crop_signals.append(f"chart_to_table:n={chart_out.n_points}")
                chart_packet_note = (
                    f"Chart packet: figure_class={figure_class}; "
                    f"chart_to_table=csv({chart_out.n_points} points); "
                    "prefer this chart crop over generic page or panel packets "
                    "for visual interpolation."
                )
            else:
                crop_signals.append("chart_to_table:empty")
                chart_extraction_confidence = chart_out.confidence
                chart_packet_note = (
                    f"Chart packet: figure_class={figure_class}; "
                    "chart_to_table=empty; prefer this chart crop over generic "
                    "page or panel packets for visual interpolation."
                )
        except Exception as exc:  # noqa: BLE001 — chart extraction is advisory
            crop_signals.append("chart_to_table:error")
            chart_packet_note = (
                f"Chart packet: figure_class={figure_class}; "
                "chart_to_table=error; prefer this chart crop over generic "
                "page or panel packets for visual interpolation."
            )
            logger.debug("chart_to_table failed for %s: %s", packet_id, exc)
    if chart_packet_note:
        scale_hint = _chart_scale_hint(ocr_snippet, question_text=question_text)
        if scale_hint:
            crop_signals.append("chart_scale_hint")
            chart_packet_note = f"{chart_packet_note} {scale_hint}"
        ocr_snippet = _prepend_chart_note(ocr_snippet, chart_packet_note)
    if _has_chart_context_crop(multi_scale_crops) and not _chart_context_needed(
        ocr_snippet,
        question_text=question_text,
    ):
        multi_scale_crops = [c for c in multi_scale_crops if c.scale != "chart_context"]
        if len(multi_scale_crops) == 1 and multi_scale_crops[0].scale == "tight":
            multi_scale_crops = []
        crop_signals = [s for s in crop_signals if "chart_context" not in s]

    commit_level = "image" if is_visual else "element"
    provenance_tool = "deterministic_inspector" if crop_signals else "skeleton_inspector_fallback"
    return EvidencePacket(
        packet_id=packet_id,
        page=region.page,
        bbox_norm=region.bbox_norm,
        region_type=region.region_type,
        page_thumbnail_ref=page_thumbnail_ref,
        local_crop_ref=crop_ref,
        multi_scale_crops=multi_scale_crops,
        ocr_snippet=ocr_snippet,
        text_layer_snippet=text_layer_snippet,
        chart_csv=chart_csv,
        chart_extraction_confidence=chart_extraction_confidence,
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


def _region_is_chart(region: RegionCandidate) -> bool:
    """True when the region's figure_class signals a chart we can extract.

    figure_class is carried as `figure_class=<name>` by the localizer and
    has historically appeared as `figure_class:<name>` in tests/older traces.
    We accept both so chart_to_table gates on the layout endpoint's chart
    classification instead of silently missing live detections.
    """
    return (_figure_class(region) or "") in _CHART_FIGURE_CLASSES


def _prepend_chart_note(ocr_snippet: str | None, note: str) -> str:
    if ocr_snippet:
        return f"{note} OCR: {ocr_snippet}"
    return note


def _chart_scale_hint(ocr_snippet: str | None, *, question_text: str | None = None) -> str | None:
    """Extract compact oscilloscope/chart scale hints from OCR text.

    Many datasheet waveform plots do not expose ordinary numeric axis ticks.
    Instead the meaningful conversion appears as labels such as
    `VOUT (400mV/div)` or `Time (2.5us/div)`. These hints are cheap to expose
    in the packet text and make empty chart_to_table attempts less opaque.
    """
    if not ocr_snippet:
        return None
    seen: set[str] = set()
    hints: list[str] = []
    hints_by_label: dict[str, str] = {}
    for match in _CHART_SCALE_RE.finditer(ocr_snippet):
        label = " ".join(match.group("label").replace("_", " ").split())
        label = _normalize_chart_label(label)
        value = match.group("value")
        unit = _normalize_chart_unit(match.group("unit"))
        if not label:
            label = "scale"
        hint = f"{label}={value}{unit}/div"
        key = hint.lower()
        if key in seen:
            continue
        seen.add(key)
        hints.append(hint)
        hints_by_label[label.upper()] = hint
        if len(hints) >= 4:
            break
    if not hints:
        return None
    sentences = ["Detected chart scales: " + "; ".join(hints) + "."]
    target = _target_chart_label(question_text)
    if target and target in hints_by_label:
        sentences.append(f"Question target scale: {hints_by_label[target]}.")
        if target in {"VOUT", "VIN"}:
            sentences.append(
                "For waveform values, count vertical divisions from the plot's "
                "zero/reference gridline using the target curve's scale."
            )
    return " ".join(sentences)


def _has_chart_context_crop(crops: list[CropRef]) -> bool:
    return any(c.scale == "chart_context" for c in crops)


def _chart_context_needed(ocr_snippet: str | None, *, question_text: str | None = None) -> bool:
    """Keep wider chart context only when the tight packet text is weak.

    If OCR already surfaced the question-target per-division scale, the wider
    crop can add adjacent subplots and distract the VLM. When the tight crop
    lacks those labels, the wider crop is still useful for axes/legends.
    """
    if not ocr_snippet or not ocr_snippet.strip():
        return True
    normalized = " ".join(ocr_snippet.lower().split())
    target = _target_chart_label(question_text)
    if target and f"question target scale: {target.lower()}=" in normalized:
        return False
    return target is not None or "detected chart scales:" not in normalized


def _needs_visual_context_crop(question_family: str | None) -> bool:
    return (question_family or "") in _VISUAL_CONTEXT_QUESTION_FAMILIES


def _allow_proactive_context_crop(
    question_family: str | None,
    region: RegionCandidate,
    *,
    packet_index: int,
) -> bool:
    """Keep same-packet context selective for broad chart/legend questions.

    Multi-chart and legend-binding examples were the noisiest branch-tip
    families: several wrong runs handed the reasoner context crops for nearly
    every visual packet. Keep the useful top-of-list signal, but avoid turning
    every sibling panel into another image unless the reranker gave no signal.
    """
    family = question_family or ""
    if family not in _BROAD_VISUAL_CONTEXT_QUESTION_FAMILIES:
        return True
    if packet_index >= _BROAD_VISUAL_CONTEXT_MAX_PACKETS:
        return False
    if region.needed_for == "primary":
        return True
    if region.relevance is None:
        return True
    return region.relevance >= _BROAD_VISUAL_CONTEXT_MIN_RELEVANCE


def _target_chart_label(question_text: str | None) -> str | None:
    if not question_text:
        return None
    normalized = _normalize_chart_label(question_text)
    for preferred in ("VOUT", "VIN", "TIME"):
        if preferred in normalized:
            return preferred
    return None


def _normalize_chart_label(label: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_+ \-]+", "", label).strip()
    normalized = cleaned.upper().replace("VOUR", "VOUT").replace("VINY", "VIN")
    normalized = normalized.replace("V_OUT", "VOUT").replace("V OUT", "VOUT")
    normalized = normalized.replace("V_IN", "VIN").replace("V IN", "VIN")
    for preferred in ("VOUT", "VIN", "TIME"):
        if preferred in normalized:
            return preferred
    return normalized


def _normalize_chart_unit(unit: str) -> str:
    normalized = unit.replace("µ", "u")
    if normalized.lower() in {"us", "uv"}:
        return normalized.lower()
    return normalized


def _packet_question_overlap(question: str, packet: EvidencePacket) -> int:
    """Tiny post-OCR relevance pass for dense chart pages.

    The localizer often returns every subplot on a datasheet page. Once OCR has
    surfaced labels/units, prefer packets whose visible text matches the asked
    series or unit (e.g. V_OUT + mV) while preserving the existing rank for ties.
    """
    q_tokens = _normalized_tokens(question)
    if not q_tokens:
        return 0
    packet_text = " ".join(
        part
        for part in (
            packet.text_layer_snippet,
            packet.ocr_snippet,
            packet.chart_csv,
            packet.region_type,
        )
        if part
    )
    p_tokens = _normalized_tokens(packet_text)
    if not p_tokens:
        return 0
    score = len(q_tokens & p_tokens)
    if packet.chart_csv:
        score += 2
    return score


def _normalized_tokens(text: str) -> set[str]:
    s = str(text).lower()
    replacements = {
        "v_out": "vout",
        "v out": "vout",
        "v-output": "vout",
        "vour": "vout",
        "vout": "vout",
        "v_in": "vin",
        "v in": "vin",
        "viny": "vin",
        "millivolts": "mv",
        "millivolt": "mv",
    }
    for old, new in replacements.items():
        s = s.replace(old, new)
    s = re.sub(r"(\d)\s*mv\b", r"\1 mv", s)
    return {tok for tok in _TOKEN_RE.findall(s) if len(tok) > 1 and tok not in _QUESTION_STOPWORDS}


def _figure_class(region: RegionCandidate) -> str | None:
    for sig in region.supporting_signals or []:
        if sig.startswith("figure_class:") or sig.startswith("figure_class="):
            separator = ":" if ":" in sig else "="
            fc = sig.split(separator, 1)[1].strip().lower()
            return fc or None
    return None


def _bbox_area(bbox: tuple[float, float, float, float]) -> float:
    """Return normalized [0,1]² area of a bbox. Negative-shaped bboxes → 0."""
    x0, y0, x1, y1 = bbox
    w = max(0.0, x1 - x0)
    h = max(0.0, y1 - y0)
    return w * h


def _crop_page_image(
    page_image: Path,
    bbox: tuple[float, float, float, float],
    *,
    cache_dir: Path | None,
    expansion: float,
) -> str:
    """Crop an already-rendered page PNG when the source PDF is unavailable."""
    if not page_image.exists():
        raise FileNotFoundError(f"page image not found: {page_image}")

    effective_cache_dir = cache_dir or (Path.cwd() / "cache" / "crops")
    effective_cache_dir.mkdir(parents=True, exist_ok=True)
    crop_path = effective_cache_dir / f"{_page_image_crop_key(page_image, bbox, expansion)}.png"
    if crop_path.exists():
        return str(crop_path)

    from PIL import Image

    with Image.open(page_image) as img:
        img = img.convert("RGB")
        crop_bbox = _bbox_norm_to_pixel(
            bbox,
            width=img.width,
            height=img.height,
            expansion=expansion,
        )
        img.crop(crop_bbox).save(crop_path, format="PNG")
    return str(crop_path)


def _page_image_crop_key(
    page_image: Path,
    bbox: tuple[float, float, float, float],
    expansion: float,
) -> str:
    stat = page_image.stat()
    h = hashlib.sha256()
    h.update(str(page_image.resolve()).encode())
    h.update(f"\0{stat.st_size}\0{stat.st_mtime_ns}\0".encode())
    h.update(",".join(f"{v:.8f}" for v in bbox).encode())
    h.update(f"\0exp={expansion:.4f}".encode())
    return h.hexdigest()


def _bbox_norm_to_pixel(
    bbox: tuple[float, float, float, float],
    *,
    width: int,
    height: int,
    expansion: float,
) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = bbox
    if not (0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0):
        raise ValueError(f"bbox_norm must be a non-empty [0,1] rectangle; got {bbox}")
    x0 = max(0.0, x0 - expansion)
    y0 = max(0.0, y0 - expansion)
    x1 = min(1.0, x1 + expansion)
    y1 = min(1.0, y1 + expansion)
    return (
        int(x0 * width),
        int(y0 * height),
        int(x1 * width),
        int(y1 * height),
    )


def _ocr_existing_crop(crop_path: Path) -> tuple[str | None, float]:
    """Run the same best-effort OCR helper used by `inspect_region` on a PNG crop."""
    try:
        from focusparse.tools.inspect_region import _ocr_crop
    except ImportError:
        return None, 0.0
    return _ocr_crop(crop_path)


def _expand_bbox(
    bbox: tuple[float, float, float, float],
    *,
    pad: float,
) -> tuple[float, float, float, float]:
    """Pad a normalized bbox by `pad` on each side (clamped to [0,1]).

    Used by the multi-scale inspector path to produce a "context" crop
    around the same target region. `pad=0.30` widens by ~30% of page on
    each side; the resulting bbox is then sliced via inspect_region with
    `expansion="none"` so we don't double-pad.
    """
    x0, y0, x1, y1 = bbox
    return (
        max(0.0, x0 - pad),
        max(0.0, y0 - pad),
        min(1.0, x1 + pad),
        min(1.0, y1 + pad),
    )


async def _zoom_crop(
    *,
    crop_ref: str,
    cache_dir: Path | None,
    packet_id: str,
) -> str | None:
    """LANCZOS upsample `crop_ref` via the run_python sandbox.

    Returns the path to the zoomed PNG (so the packet's `local_crop_ref`
    can swap to it) or None on any failure (silent — keep the original
    crop). Tiny crops get a true 2× resize; larger retry crops are capped
    by `_AUTOZOOM_MAX_DIM`. Cache dir is the same content-addressed dir
    `inspect_region` writes to; the upsampled PNG goes there too keyed
    by sha256(bytes).
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


def _rank_score(
    region: RegionCandidate,
    boosted_types: frozenset[str],
    *,
    wants_chart: bool = False,
) -> float:
    """Score used only for top-N selection; packet.confidence still carries
    the raw detector score.

    Layered query-conditioning (signals stack multiplicatively):
      1. Detector score — RT-DETRv2 confidence in this region.
      2. Evidence-type boost (×1.5) when the planner asked for this kind.
      3. Chart-subclass adjustment when the query needs chart evidence:
         chart-class figures get promoted; logos and generic picture
         containers are damped so they don't crowd out actual plots.
      4. Reranker relevance (Phase 2 item 4) — when present, multiplies
         the score by `relevance` directly. The reranker is a mid-tier
         LLM that read the question; it's the best per-region relevance
         signal we have. Sprint 2026-05-05 (Phase B3) hook.
      5. Reranker `needed_for=primary` boost (×1.3) — the rerank stage
         tagged this region as the answer carrier; pull it forward even
         when its detector score is mediocre.

    When neither rerank nor planner signal is present, falls back to
    raw detector score (the pre-rerank skeleton ordering).
    """
    base = float(region.score)
    boosted = base
    if boosted_types:
        rtype = (region.region_type or "").lower()
        if rtype and rtype in boosted_types:
            boosted = base * _EVIDENCE_TYPE_BOOST
    if wants_chart and (region.region_type or "").lower() in _VISUAL_REGION_TYPES:
        figure_class = _figure_class(region)
        if figure_class in _CHART_FIGURE_CLASSES:
            boosted *= 1.5
        elif figure_class == "logo":
            boosted *= 0.25
        elif figure_class == "other":
            boosted *= 0.45
    # Layer the reranker signals on top of the type-boosted score.
    if region.relevance is not None:
        # Reranker scored 0..1; treat 0.5 as neutral.
        # `relevance × 2` keeps the magnitude similar to base score units
        # (so a perfectly-relevant region effectively doubles).
        boosted *= max(0.1, 2.0 * float(region.relevance))
    if region.needed_for == "primary":
        boosted *= 1.3
    return boosted


def _select_regions_for_inspection(
    ranked_regions: list[RegionCandidate],
    *,
    max_crops: int,
    plan: PlanEvent,
) -> list[RegionCandidate]:
    """Pick inspector regions while preserving multi-page evidence coverage.

    The upstream router can intentionally surface multiple pages for questions
    that need a table plus a schematic, or a caption plus a chart. A pure
    global top-N can spend all slots on one high-confidence text-heavy page.
    For multi-region plans, reserve the best region from each routed page
    before filling remaining slots by the existing score order.
    """
    if max_crops <= 0:
        return []
    if len(ranked_regions) <= max_crops:
        return list(ranked_regions)
    if not _plan_needs_page_diversity(plan):
        return ranked_regions[:max_crops]

    selected: list[RegionCandidate] = []
    selected_ids: set[str] = set()
    seen_pages: set[int] = set()
    for region in ranked_regions:
        if region.page in seen_pages:
            continue
        seen_pages.add(region.page)
        selected.append(region)
        selected_ids.add(region.region_id)
        if len(selected) >= max_crops:
            return selected

    for region in ranked_regions:
        if region.region_id in selected_ids:
            continue
        selected.append(region)
        if len(selected) >= max_crops:
            break
    return selected


def _plan_needs_page_diversity(plan: PlanEvent) -> bool:
    budget_class = (plan.budget_class or "").lower()
    if budget_class in {"multi_region", "multi-page", "multi_page"}:
        return True
    evidence_types = {(item or "").strip().lower() for item in plan.evidence_types}
    return len(evidence_types & {"diagram", "figure", "table", "text", "caption", "footnote"}) >= 2
