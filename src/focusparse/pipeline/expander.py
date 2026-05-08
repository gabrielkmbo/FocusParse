"""EXPAND_CONTEXT stage — attach linked neighbor regions to each evidence packet.

Sub-phase 2h makes this real. The inspector picks top-N regions and emits
packets, but those packets are "naked" — a figure without its caption,
a table without its header row, a spec cell without its column label.
The reasoner then has to guess context that was visible a few pixels
away.

This stage consults the localizer's full region list (not just the
inspector's top-N) and, for each packet, attaches up to
`max_neighbors_per_packet` spatially-adjacent "annotation" regions:
caption, footnote, section_header, title, page-header/footer. Each
neighbor is cropped via `inspect_region(mode='image')` and its path is
added to `linked_crop_refs`, its type to `linked_neighbor_types`.

Adjacency is an overlap test against the packet bbox expanded by a
small pad (default 8% of page dims). This catches captions immediately
below a figure, footnotes at the bottom of a chart, and section
headers above a table, while filtering unrelated regions on the other
side of the page.

When `regions` or both crop sources (`pdf_path` and `images_by_page`) are
unavailable the stage returns evidence unchanged — downstream stages get exactly
the pre-2h passthrough behavior, preserving every existing caller.
"""

from __future__ import annotations

import hashlib
import logging
import re
from io import BytesIO
from pathlib import Path

from focusparse.evidence.packet import CropRef, EvidencePacket, PacketProvenance
from focusparse.pipeline.events import EvidenceEvent, PlanEvent, RegionCandidate, RegionsEvent
from focusparse.pipeline.evidence_graph import (
    extract_figure_class,
    find_graph_neighbors,
    has_graph_entry,
)
from focusparse.pipeline.inspector import _crop_page_image, _ocr_existing_crop, _zoom_crop
from focusparse.tools.get_text_layer import GetTextLayerInput, get_text_layer
from focusparse.tools.inspect_region import InspectRegionInput, inspect_region

logger = logging.getLogger(__name__)

# Region types that annotate a nearby primary region. Intentionally tight —
# other pictures / text blocks are not "annotations", they're siblings.
_NEIGHBOR_TYPES: frozenset[str] = frozenset(
    {
        "axis-label",
        "axis_label",
        "caption",
        "footnote",
        "legend",
        "section_header",
        "section-header",
        "title",
        "page-header",
        "page-footer",
    }
)

# Map planner-vocab `evidence_types` (e.g. "caption", "footnote", "header") to
# detector-vocab region_types the expander considers as neighbors. Mirrors
# `inspector._EVIDENCE_TYPE_ALIASES` but scoped to *neighbor* selection — we
# never attach "figure" or "chart" as a neighbor because those are siblings,
# not annotations.
_EVIDENCE_TYPE_TO_NEIGHBOR_TYPES: dict[str, frozenset[str]] = {
    "axis": frozenset({"axis-label", "axis_label"}),
    "axis_label": frozenset({"axis-label", "axis_label"}),
    "axis-label": frozenset({"axis-label", "axis_label"}),
    "caption": frozenset({"caption"}),
    "column_header": frozenset({"page-header", "section_header", "section-header", "title"}),
    "continuation": frozenset(
        {"page-header", "page-footer", "section_header", "section-header", "title"}
    ),
    "footnote": frozenset({"footnote"}),
    "header": frozenset({"page-header", "section_header", "section-header", "title"}),
    "footer": frozenset({"page-footer"}),
    "chart": frozenset({"axis-label", "axis_label", "caption", "legend", "title"}),
    "legend": frozenset({"legend"}),
    "row_header": frozenset({"page-header", "section_header", "section-header", "title"}),
    "table": frozenset(
        {"caption", "footnote", "page-header", "section_header", "section-header", "title"}
    ),
    "title": frozenset({"title", "section_header", "section-header"}),
    "section_header": frozenset({"section_header", "section-header", "title"}),
    "unit": frozenset({"axis-label", "axis_label", "caption", "legend"}),
    "x_axis": frozenset({"axis-label", "axis_label"}),
    "y_axis": frozenset({"axis-label", "axis_label"}),
}

# Reranker `needed_for` roles that indicate "this region is a context
# dependency for the focus region." When the reranker (Phase 2 item 4)
# tags a candidate with one of these, the expander attaches it even
# without an explicit `plan.evidence_types` request.
_RERANK_CONTEXT_ROLES: frozenset[str] = frozenset(
    {
        "legend_binding",
        "axis_reading",
        "caption_context",
        "footnote_adjustment",
        "table_cell_lookup",
        "header_disambiguation",
    }
)

# Minimum reranker `relevance` for a neighbor to be attached when the
# reranker scored it but didn't tag a context role. Tuned 0.3 → 0.5 on
# 2026-05-05 (Phase B1.5) after the B1 A/B showed ~20% of packets still
# attached 3-4 neighbors with relevance just above 0.3. Reasoner image
# budget is finite; lower relevance scores fail to discriminate.
_DEFAULT_NEIGHBOR_RELEVANCE_THRESHOLD = 0.5

# Per-packet neighbor cap. Tightened 4 → 2 on 2026-05-05 (Phase B1.5).
# B1's max=4 produced too many marginal-relevance neighbors per packet
# (mean 1.4 attached, distribution skewed: 20% of packets got 3-4).
# At 2 per packet, even chart-heavy questions stay within a tolerable
# image budget for the reasoner.
_DEFAULT_MAX_NEIGHBORS_PER_PACKET = 2
# Even tighter cap when the planner gave no `evidence_types` hint AND
# the reranker didn't run. Halves the spatial-only-fallback budget so
# a query-blind expansion can't dominate the reasoner's image budget.
_FALLBACK_MAX_NEIGHBORS_PER_PACKET = 1
# First-pass expansion with reranker scores can still flood the reasoner when
# many inspected packets look relevant. Keep the initial evidence budget small;
# verifier-directed retries remain target-packet based and are not capped here.
_INITIAL_RERANKED_TOTAL_NEIGHBOR_CAP = 6
_INITIAL_CAP_EXEMPT_QUESTION_FAMILIES = frozenset(
    {
        "axis_value_interpolation",
        "chart_caption_fusion",
        "chart_footnote_fusion",
        "chart_table_cross_ref",
        "curve_axis_reading",
        "dual_axis_disambiguation",
        "legend_series_binding",
        "multi_chart_comparison",
        "timing_diagram_reading",
    }
)
# Expand the packet's bbox by this fraction of the [0,1] range on each side
# when testing for neighbor overlap. 0.08 ≈ ~1 inch on a Letter page at 300
# DPI — enough to catch a caption a few text lines away.
_DEFAULT_ADJACENCY_PAD = 0.08
_RETRY_CONTEXT_WINDOW_PAD = 0.24
_MAX_VISUAL_ZOOM_RETRY_PACKETS = 2
_RETRY_VISUAL_ZOOM_MAX_DIM = 2048
_MAX_LINKED_CONTEXT_TEXT_CHARS = 240
_FIGURE_REF_RE = re.compile(r"\b(?:fig(?:ure)?\.?)\s*(?P<num>\d+[A-Za-z]?)\b", re.IGNORECASE)
_CONTEXT_LINE_RE = re.compile(r"^Context\s+\[[^\]]+\]:\s*(?P<text>.*)$", re.IGNORECASE)
_CONTEXT_WINDOW_REGION_TYPES: frozenset[str] = frozenset(
    {
        "bar_chart",
        "candlestick",
        "caption",
        "chart",
        "code",
        "curve",
        "diagram",
        "figure",
        "form",
        "image",
        "key-value region",
        "key_value_region",
        "line_chart",
        "list-item",
        "list_item",
        "picture",
        "plot",
        "table",
        "text",
    }
)


async def expand_context(
    evidence: EvidenceEvent,
    *,
    regions: RegionsEvent | None = None,
    pdf_path: Path | None = None,
    images_by_page: dict[int, Path] | None = None,
    crop_cache_dir: Path | None = None,
    text_layer_cache_dir: Path | None = None,
    max_neighbors_per_packet: int = _DEFAULT_MAX_NEIGHBORS_PER_PACKET,
    adjacency_pad: float = _DEFAULT_ADJACENCY_PAD,
    use_evidence_graph: bool = False,
    plan: PlanEvent | None = None,
    verifier_reason: str | None = None,
    target_packet_ids: list[str] | None = None,
    relevance_threshold: float = _DEFAULT_NEIGHBOR_RELEVANCE_THRESHOLD,
    retry_visual_zoom: bool = False,
) -> EvidenceEvent:
    """Attach annotation neighbors to each packet, or pass through unchanged.

    Args:
        evidence: packets from the inspector.
        regions: full `RegionsEvent` from the localizer. When None, the
            stage is a passthrough — we need the full region list to find
            neighbors the inspector didn't promote to a packet.
        pdf_path: source PDF. Preferred for cropping/OCR of neighbor regions.
            When unavailable, the expander can still crop already-rendered page
            PNGs from `images_by_page`.
        images_by_page: optional 1-indexed page -> rendered page PNG fallback
            used when `pdf_path` is unavailable.
        crop_cache_dir: where neighbor crop PNGs go. Content-addressed by
            `inspect_region` so repeated calls on the same region are free.
        text_layer_cache_dir: optional cache dir for native text snippets
            extracted from attached neighbor regions.
        max_neighbors_per_packet: cap (plan §2e says 4 to keep packets
            compact). Halved automatically when neither `plan` nor the
            reranker provided a relevance signal (see
            `_FALLBACK_MAX_NEIGHBORS_PER_PACKET`).
        adjacency_pad: fractional bbox expansion for the overlap test.
        plan: optional `PlanEvent`. When provided, `plan.evidence_types`
            filters neighbor candidates to types the planner asked for
            (e.g. "caption" → only attach captions).
        verifier_reason: optional unsupported-verdict reason from a verifier
            retry. Mentions like "missing legend" or "needs footnote" add
            targeted neighbor types even if the original planner hint was
            narrower. Without `verifier_reason` or reranker relevance scores,
            the expander uses a tighter initial budget even when the planner
            supplied coarse hints — the rebaseline-v2 finding (2026-05-05)
            showed that broad expansion attached ~13 neighbors per example
            and hurt 11 of 13 affected examples.
        target_packet_ids: optional packet ids to expand. Verifier-driven
            retries use this to avoid adding fresh context to packets the
            answer did not cite. ``None`` means expand all eligible packets
            (initial pass); an explicit empty list means expand none.
        relevance_threshold: when the reranker (Phase 2 item 4) scored
            candidates, neighbors below this threshold are filtered out
            even if they overlap spatially. Default 0.3.

    Returns:
        An `EvidenceEvent` with the same packets, each potentially carrying
        `linked_crop_refs` / `linked_neighbor_types` / updated provenance.
    """
    if regions is None or (pdf_path is None and not images_by_page):
        return evidence

    if retry_visual_zoom:
        zoomed = await _expand_retry_visual_zoom(
            evidence,
            crop_cache_dir=crop_cache_dir,
            target_packet_ids=target_packet_ids,
        )
        if _zoom_added(evidence, zoomed):
            return zoomed

    # Resolve which neighbor region_types the planner permits. Empty set
    # means "no planner hint" → fall back to the conservative budget.
    permitted_neighbor_types = _resolve_permitted_neighbor_types(
        plan,
        verifier_reason=verifier_reason,
    )
    has_planner_hint = bool(permitted_neighbor_types)
    has_rerank_signal = any(
        c.relevance is not None or c.needed_for is not None for c in regions.candidates
    )
    effective_max = (
        max_neighbors_per_packet
        if (verifier_reason or has_rerank_signal)
        else _FALLBACK_MAX_NEIGHBORS_PER_PACKET
    )

    # Group regions by page so the per-packet lookup is O(regions_on_page),
    # not O(total_regions). For long docs this matters.
    regions_by_page: dict[int, list[RegionCandidate]] = {}
    for r in regions.candidates:
        regions_by_page.setdefault(r.page, []).append(r)

    new_packets: list[EvidencePacket] = []
    target_filter_active = target_packet_ids is not None
    target_set = {pid for pid in (target_packet_ids or []) if pid}
    total_new_neighbor_cap = (
        _INITIAL_RERANKED_TOTAL_NEIGHBOR_CAP
        if _should_cap_initial_reranked_expansion(
            plan,
            has_rerank_signal=has_rerank_signal,
            verifier_reason=verifier_reason,
            target_filter_active=target_filter_active,
        )
        else None
    )
    total_new_neighbor_links = 0
    for packet in evidence.packets:
        if target_filter_active and packet.packet_id not in target_set:
            new_packets.append(packet)
            continue
        candidates_on_page = regions_by_page.get(packet.page, [])
        # Find the matching RegionCandidate so we can read figure_class +
        # expansion_hints (populated by item 4's reranker).
        primary_region = _match_primary_region(packet, candidates_on_page)
        if not _should_initially_expand_packet(
            primary_region,
            has_rerank_signal=has_rerank_signal,
            verifier_reason=verifier_reason,
            target_filter_active=target_filter_active,
            relevance_threshold=relevance_threshold,
        ):
            new_packets.append(packet)
            continue

        # Graph walker is opt-in (default off) since the n=30 A/B on
        # 2026-04-27 showed it regressed region_recall (-0.113),
        # bbox_iou (-0.056), and region_precision (-0.046) vs the
        # spatial-overlap heuristic. Wiring + tests stay so we can
        # opt in once the graph rules are tuned (likely culprits:
        # too-strict directional constraints, too-narrow max_distance).
        figure_class = (
            extract_figure_class(primary_region)
            if (use_evidence_graph and primary_region)
            else None
        )
        graph_matches: list[tuple[RegionCandidate, str]] = []
        existing_link_count = len([ref for ref in packet.linked_crop_refs if ref])
        candidate_limit = max_neighbors_per_packet + existing_link_count
        new_link_cap = effective_max
        remaining_total_links: int | None = None
        if total_new_neighbor_cap is not None:
            remaining_total_links = total_new_neighbor_cap - total_new_neighbor_links
            if remaining_total_links <= 0:
                new_packets.append(packet)
                continue
            new_link_cap = min(new_link_cap, remaining_total_links)
            candidate_limit = min(candidate_limit, existing_link_count + new_link_cap)
        if use_evidence_graph and has_graph_entry(packet.region_type, figure_class):
            hints = primary_region.expansion_hints if primary_region else None
            graph_matches = find_graph_neighbors(
                primary_region or _synth_primary_from_packet(packet),
                candidates_on_page,
                expansion_hints=hints,
            )[:candidate_limit]
            new_link_cap = max_neighbors_per_packet
            if remaining_total_links is not None:
                new_link_cap = min(new_link_cap, remaining_total_links)

        if graph_matches:
            neighbors_with_role: list[tuple[RegionCandidate, str]] = list(graph_matches)
        else:
            # Fallback: spatial-overlap heuristic, but query-aware (filter
            # by planner evidence_types and/or reranker relevance/needed_for).
            spatial = _pick_neighbors(
                packet,
                candidates_on_page,
                max_n=candidate_limit,
                pad=adjacency_pad,
                permitted_neighbor_types=permitted_neighbor_types,
                has_planner_hint=has_planner_hint,
                relevance_threshold=relevance_threshold,
            )
            neighbors_with_role = [(n, _neighbor_role(n)) for n in spatial]

        context_window_ref = None
        context_window_text = None
        context_window_bbox = None
        if _should_attach_retry_context_window(
            packet,
            verifier_reason=verifier_reason,
            target_filter_active=target_filter_active,
        ):
            context_window_bbox = _context_window_bbox(packet)
            context_window_ref = await _crop_context_window(
                packet,
                pdf_path=pdf_path,
                page_image=(images_by_page or {}).get(packet.page),
                crop_cache_dir=crop_cache_dir,
                bbox=context_window_bbox,
            )
            if context_window_ref and context_window_bbox is not None:
                context_window_text = await _extract_neighbor_text(
                    _synth_context_window_region(packet, context_window_bbox),
                    role="context_window",
                    pdf_path=pdf_path,
                    crop_ref=context_window_ref,
                    text_layer_cache_dir=text_layer_cache_dir,
                    crop_cache_dir=crop_cache_dir,
                )

        if not neighbors_with_role and context_window_ref is None:
            new_packets.append(packet)
            continue

        linked_refs: list[str] = list(packet.linked_crop_refs)
        linked_types: list[str] = list(packet.linked_neighbor_types)
        linked_texts: list[tuple[str, str]] = []
        seen_linked_refs = {ref for ref in linked_refs if ref}
        n_new_links = 0
        n_new_neighbor_links = 0
        if context_window_ref and context_window_ref not in seen_linked_refs:
            linked_refs.append(context_window_ref)
            linked_types.append("context_window")
            if context_window_text:
                linked_texts.append(("context_window", context_window_text))
            seen_linked_refs.add(context_window_ref)
            n_new_links += 1
        packet_figure_refs = _figure_refs_from_text(packet.text_layer_snippet, packet.ocr_snippet)
        for neighbor, role in neighbors_with_role:
            if n_new_neighbor_links >= new_link_cap:
                break
            crop_ref = await _crop_neighbor(
                neighbor,
                pdf_path=pdf_path,
                page_image=(images_by_page or {}).get(neighbor.page),
                crop_cache_dir=crop_cache_dir,
            )
            if crop_ref is None:
                continue
            if crop_ref in seen_linked_refs:
                continue
            linked_text = await _extract_neighbor_text(
                neighbor,
                role=role,
                pdf_path=pdf_path,
                crop_ref=crop_ref,
                text_layer_cache_dir=text_layer_cache_dir,
                crop_cache_dir=crop_cache_dir,
            )
            if linked_text:
                if _neighbor_text_mismatches_packet_figure(
                    packet_figure_refs,
                    role=role,
                    linked_text=linked_text,
                ):
                    continue
                linked_texts.append((role, linked_text))
            linked_refs.append(crop_ref)
            # Use the graph's semantic role (caption / title / footnote /
            # legend / axis) when present; falls back to the raw region_type
            # for spatial-heuristic matches.
            linked_types.append(role)
            seen_linked_refs.add(crop_ref)
            n_new_links += 1
            n_new_neighbor_links += 1

        if n_new_links == 0:
            new_packets.append(packet)
            continue
        total_new_neighbor_links += n_new_neighbor_links

        updates = {
            "linked_crop_refs": linked_refs,
            "linked_neighbor_types": linked_types,
            "provenance": _updated_provenance(packet.provenance, n_new_links),
        }
        updates.update(_context_text_updates(packet, linked_texts))
        new_packets.append(packet.model_copy(update=updates))
    return EvidenceEvent(packets=new_packets)


# ---------------------------------------------------------------------------
# Neighbor picking
# ---------------------------------------------------------------------------


def _pick_neighbors(
    packet: EvidencePacket,
    candidates: list[RegionCandidate],
    *,
    max_n: int,
    pad: float,
    permitted_neighbor_types: frozenset[str] | None = None,
    has_planner_hint: bool = False,
    relevance_threshold: float = _DEFAULT_NEIGHBOR_RELEVANCE_THRESHOLD,
) -> list[RegionCandidate]:
    """Return up to `max_n` context regions adjacent to `packet`.

    Selection (query-aware as of 2026-05-05):
      * region_type must be in `_NEIGHBOR_TYPES`, OR the reranker must tag
        the region with a context `needed_for` role
      * must not BE the packet region (same bbox / same region_id)
      * padded packet bbox must overlap the candidate bbox
      * AND at least one of the following:
        - region_type ∈ permitted_neighbor_types (planner asked for this kind)
        - cand.needed_for ∈ _RERANK_CONTEXT_ROLES (reranker tagged it as a
          context dependency for this question)
        - cand.relevance ≥ relevance_threshold (reranker scored it relevant)
        - has_planner_hint is False AND cand.relevance is None (legacy
          spatial-only fallback when no signals are present — capped by
          the smaller `_FALLBACK_MAX_NEIGHBORS_PER_PACKET` upstream)

    Ordering: most-relevant first.
      * Reranker-scored candidates outrank unscored ones (by relevance desc).
      * Within unscored candidates: vertical distance ascending, then
        detector score descending.
    """
    if not candidates:
        return []
    permitted = permitted_neighbor_types or frozenset()
    packet_bbox = _pad_bbox(packet.bbox_norm, pad=pad)
    px_center_y = (packet.bbox_norm[1] + packet.bbox_norm[3]) / 2.0

    # Sort key tuple: (rerank_bucket, primary, secondary, tertiary).
    # rerank_bucket: 0 = had relevance score; 1 = had needed_for role only;
    #                2 = passed because planner asked for this region_type;
    #                3 = legacy spatial-only fallback.
    matches: list[tuple[int, float, float, float, RegionCandidate]] = []
    for cand in candidates:
        ctype = (cand.region_type or "").lower()
        has_context_role = cand.needed_for in _RERANK_CONTEXT_ROLES
        if ctype not in _NEIGHBOR_TYPES and ctype not in permitted and not has_context_role:
            continue
        if _bbox_equal(cand.bbox_norm, packet.bbox_norm):
            continue
        if not _bbox_overlaps(packet_bbox, cand.bbox_norm):
            continue

        # Query-aware relevance gate.
        rerank_bucket: int | None = None
        primary: float = 0.0
        if cand.needed_for and cand.needed_for in _RERANK_CONTEXT_ROLES:
            rerank_bucket = 1
            primary = -float(cand.relevance or 0.5)  # higher relevance = better
        elif cand.relevance is not None:
            if cand.relevance < relevance_threshold:
                continue  # reranker scored it but said it's not relevant
            rerank_bucket = 0
            primary = -float(cand.relevance)
        elif ctype in permitted:
            rerank_bucket = 2
            primary = 0.0
        elif not has_planner_hint:
            # Legacy spatial-only fallback (no planner hint, no reranker).
            # Caller's `max_n` is already halved; this branch keeps the
            # pre-2026-05-05 behavior bounded.
            rerank_bucket = 3
            primary = 0.0
        else:
            # Planner had hints but this region_type wasn't on the list and
            # the reranker didn't tag it. Drop.
            continue

        cy = (cand.bbox_norm[1] + cand.bbox_norm[3]) / 2.0
        secondary = abs(cy - px_center_y)  # vertical distance
        tertiary = -float(cand.score)
        matches.append((rerank_bucket, primary, secondary, tertiary, cand))

    matches.sort(key=lambda t: (t[0], t[1], t[2], t[3]))
    return [cand for _b, _p, _d, _s, cand in matches[:max_n]]


def _neighbor_role(cand: RegionCandidate) -> str:
    """Role descriptor shown to the reasoner for an attached neighbor."""
    ctype = (cand.region_type or "").lower()
    if ctype in _NEIGHBOR_TYPES:
        return ctype
    if cand.needed_for in _RERANK_CONTEXT_ROLES:
        return str(cand.needed_for)
    return ctype or "unknown"


def _should_initially_expand_packet(
    primary_region: RegionCandidate | None,
    *,
    has_rerank_signal: bool,
    verifier_reason: str | None,
    target_filter_active: bool,
    relevance_threshold: float,
) -> bool:
    """Gate first-pass expansion to packets with query-conditioned support.

    Once the reranker has annotated the region list, adding context to every
    inspected packet can flood the reasoner with neighbors from packets the
    reranker did not select. Verifier-directed retries are exempt: at that
    point the controller has already named target packets and missing context.
    """
    if verifier_reason or target_filter_active:
        return True
    if not has_rerank_signal or primary_region is None:
        return True
    if primary_region.needed_for == "primary":
        return True
    if primary_region.needed_for in _RERANK_CONTEXT_ROLES:
        return True
    if primary_region.expansion_hints:
        return True
    return primary_region.relevance is not None and primary_region.relevance >= relevance_threshold


def _should_cap_initial_reranked_expansion(
    plan: PlanEvent | None,
    *,
    has_rerank_signal: bool,
    verifier_reason: str | None,
    target_filter_active: bool,
) -> bool:
    """Apply the run-level context budget to text/table-ish first passes.

    Visual chart/timing families often need several sibling packets plus axes
    or legends before the first answer. Text/table families are where the
    latest full run showed large neighbor fanout without corresponding
    support, so cap them until a verifier retry names target packets.
    """
    if not has_rerank_signal or verifier_reason or target_filter_active:
        return False
    family = (plan.question_family if plan else None) or ""
    return family not in _INITIAL_CAP_EXEMPT_QUESTION_FAMILIES


def _should_attach_retry_context_window(
    packet: EvidencePacket,
    *,
    verifier_reason: str | None,
    target_filter_active: bool,
) -> bool:
    """Verifier retries add a wider crop for the cited/target packet itself."""
    if not (verifier_reason and target_filter_active):
        return False
    region_type = (packet.region_type or "").strip().lower()
    return not region_type or region_type in _CONTEXT_WINDOW_REGION_TYPES


async def _expand_retry_visual_zoom(
    evidence: EvidenceEvent,
    *,
    crop_cache_dir: Path | None,
    target_packet_ids: list[str] | None,
) -> EvidenceEvent:
    """Add a zoomed copy of cited visual crops without adding new context.

    This path is intentionally narrower than normal `expand_context`: it only
    sharpens already-selected evidence after a verifier explicitly complained
    about readability. No neighbor crops, context windows, or native text are
    added, keeping the retry's action space small.
    """
    target_set = {pid for pid in (target_packet_ids or []) if pid}
    if not target_set:
        return evidence

    zoomed = 0
    new_packets: list[EvidencePacket] = []
    for packet in evidence.packets:
        if packet.packet_id not in target_set or zoomed >= _MAX_VISUAL_ZOOM_RETRY_PACKETS:
            new_packets.append(packet)
            continue
        if _packet_has_scale(packet, "zoomed"):
            new_packets.append(packet)
            continue
        crop_ref, bbox = _tight_crop_for_zoom(packet)
        if not crop_ref:
            new_packets.append(packet)
            continue
        zoom_tag = "expand_context:visual_zoom1"
        zoom_ref = await _zoom_crop(
            crop_ref=crop_ref,
            cache_dir=crop_cache_dir,
            packet_id=packet.packet_id,
        )
        if not zoom_ref:
            zoom_ref = _direct_zoom_crop(
                crop_ref=crop_ref,
                cache_dir=crop_cache_dir,
            )
            zoom_tag = "expand_context:visual_zoom1_direct"
        if not zoom_ref:
            new_packets.append(packet)
            continue
        multi_scale = list(packet.multi_scale_crops)
        if not multi_scale:
            multi_scale.append(CropRef(ref=crop_ref, bbox_norm=bbox, scale="tight"))
        multi_scale.append(CropRef(ref=zoom_ref, bbox_norm=bbox, scale="zoomed"))
        new_packets.append(
            packet.model_copy(
                update={
                    "multi_scale_crops": multi_scale,
                    "provenance": _updated_provenance(
                        packet.provenance,
                        0,
                        tag=zoom_tag,
                    ),
                }
            )
        )
        zoomed += 1
    return EvidenceEvent(packets=new_packets)


def _tight_crop_for_zoom(
    packet: EvidencePacket,
) -> tuple[str | None, tuple[float, float, float, float]]:
    for crop in packet.multi_scale_crops:
        if crop.scale == "tight" and crop.ref:
            return crop.ref, crop.bbox_norm
    return packet.local_crop_ref or None, packet.bbox_norm


def _direct_zoom_crop(
    *,
    crop_ref: str,
    cache_dir: Path | None,
) -> str | None:
    """Deterministically upsample a crop when the sandboxed zoom path fails.

    Verifier-directed visual retries are only useful if the next reasoner call
    actually receives sharper evidence. `run_python` is still the first path,
    but transient sandbox/process failures should not collapse a readability
    retry back into ordinary neighbor expansion.
    """
    crop_path = Path(crop_ref)
    if not crop_path.exists():
        return None

    try:
        from PIL import Image
    except ImportError:
        return None

    try:
        with Image.open(crop_path) as img:
            img = img.convert("RGB")
            target_w, target_h = img.width * 2, img.height * 2
            if max(target_w, target_h) > _RETRY_VISUAL_ZOOM_MAX_DIM:
                scale = _RETRY_VISUAL_ZOOM_MAX_DIM / max(target_w, target_h)
                target_w = max(1, int(round(target_w * scale)))
                target_h = max(1, int(round(target_h * scale)))
            out = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
            buf = BytesIO()
            out.save(buf, format="PNG")
            png_bytes = buf.getvalue()
    except (OSError, ValueError):
        return None

    out_dir = Path(cache_dir) if cache_dir is not None else crop_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    ref = hashlib.sha256(png_bytes).hexdigest()[:16]
    out_path = out_dir / f"{ref}.png"
    if not out_path.exists():
        out_path.write_bytes(png_bytes)
    return str(out_path)


def _packet_has_scale(packet: EvidencePacket, scale: str) -> bool:
    return any(c.scale == scale for c in packet.multi_scale_crops)


def _zoom_added(before: EvidenceEvent, after: EvidenceEvent) -> bool:
    before_counts = {p.packet_id: _packet_scale_count(p, "zoomed") for p in before.packets}
    return any(
        _packet_scale_count(packet, "zoomed") > before_counts.get(packet.packet_id, 0)
        for packet in after.packets
    )


def _packet_scale_count(packet: EvidencePacket, scale: str) -> int:
    return sum(1 for crop in packet.multi_scale_crops if crop.scale == scale)


def _resolve_permitted_neighbor_types(
    plan: PlanEvent | None,
    *,
    verifier_reason: str | None = None,
) -> frozenset[str]:
    """Map `plan.evidence_types` (planner vocab) to the set of detector-vocab
    region_types the expander is allowed to attach as neighbors.

    Returns an empty set when `plan` is None or `evidence_types` is empty;
    callers fall back to the legacy spatial heuristic in that case (with a
    tighter neighbor cap to bound noise).
    """
    permitted: set[str] = set()
    if plan is not None:
        for raw in plan.evidence_types:
            key = (raw or "").strip().lower()
            if not key:
                continue
            aliases = _EVIDENCE_TYPE_TO_NEIGHBOR_TYPES.get(key)
            if aliases:
                permitted |= aliases
    permitted |= _neighbor_types_from_verifier_reason(verifier_reason)
    return frozenset(permitted)


def _neighbor_types_from_verifier_reason(reason: str | None) -> frozenset[str]:
    """Infer targeted context-neighbor types from verifier failure text."""
    if not reason:
        return frozenset()
    normalized = reason.lower()
    normalized = re.sub(r"[^a-z0-9_ -]+", " ", normalized)
    wanted: set[str] = set()
    token_checks: tuple[tuple[tuple[str, ...], frozenset[str]], ...] = (
        (
            ("axis label", "axis labels", "tick label", "tick labels"),
            frozenset({"axis-label", "axis_label"}),
        ),
        (("caption", "captions"), frozenset({"caption"})),
        (("footnote", "footnotes", "note", "notes"), frozenset({"footnote"})),
        (
            ("header", "headers", "row label", "column label"),
            frozenset({"page-header", "section_header", "section-header", "title"}),
        ),
        (
            (
                "cell",
                "cells",
                "column",
                "columns",
                "row",
                "rows",
                "table",
                "tables",
                "value",
                "values",
            ),
            frozenset(
                {
                    "code",
                    "key-value region",
                    "key_value_region",
                    "list-item",
                    "list_item",
                    "table",
                    "text",
                }
            ),
        ),
        (("legend", "legends"), frozenset({"legend"})),
        (("title", "section title"), frozenset({"title", "section_header", "section-header"})),
        (
            ("continuation", "continued", "previous page", "next page"),
            frozenset({"page-header", "page-footer", "section_header", "section-header", "title"}),
        ),
    )
    for needles, aliases in token_checks:
        if any(needle in normalized for needle in needles):
            wanted |= aliases
    return frozenset(wanted)


def _pad_bbox(
    bbox: tuple[float, float, float, float], *, pad: float
) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = bbox
    return (
        max(0.0, x0 - pad),
        max(0.0, y0 - pad),
        min(1.0, x1 + pad),
        min(1.0, y1 + pad),
    )


def _bbox_overlaps(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    # Strict inequality avoids zero-area "overlap" at a shared edge.
    return ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1


def _bbox_equal(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
    *,
    tol: float = 1e-6,
) -> bool:
    return all(abs(ai - bi) < tol for ai, bi in zip(a, b, strict=False))


def _match_primary_region(
    packet: EvidencePacket,
    candidates: list[RegionCandidate],
) -> RegionCandidate | None:
    """Find the RegionCandidate the packet was built from.

    Match by (page, bbox) since the inspector preserves both. Returns
    None when no exact match — the graph walker then synthesizes a
    minimal primary record from the packet alone (no expansion_hints,
    no figure_class).
    """
    for r in candidates:
        if r.page == packet.page and _bbox_equal(r.bbox_norm, packet.bbox_norm):
            return r
    return None


def _synth_primary_from_packet(packet: EvidencePacket) -> RegionCandidate:
    """Build a minimal RegionCandidate from a packet when the original
    region wasn't found in the candidates list (e.g. the inspector
    synthesized a fallback packet without a backing detection)."""
    return RegionCandidate(
        region_id=f"synth_{packet.packet_id}",
        page=packet.page,
        bbox_norm=packet.bbox_norm,
        region_type=packet.region_type,
        score=float(packet.confidence),
    )


# ---------------------------------------------------------------------------
# Neighbor cropping
# ---------------------------------------------------------------------------


async def _crop_neighbor(
    neighbor: RegionCandidate,
    *,
    pdf_path: Path | None,
    page_image: Path | None,
    crop_cache_dir: Path | None,
) -> str | None:
    """Render a cropped PNG for a neighbor region; return None on failure."""
    if pdf_path is not None:
        try:
            out = await inspect_region(
                InspectRegionInput(
                    doc_path=str(pdf_path),
                    page=neighbor.page,
                    bbox_norm=neighbor.bbox_norm,
                    mode="image",
                    expansion="none",  # neighbor bboxes are already tight
                ),
                cache_dir=crop_cache_dir,
            )
            return out.crop_ref
        except (FileNotFoundError, ValueError) as exc:
            logger.debug(
                "neighbor crop failed for page=%d bbox=%s: %s",
                neighbor.page,
                neighbor.bbox_norm,
                exc,
            )

    if page_image is not None:
        try:
            return _crop_page_image(
                page_image,
                neighbor.bbox_norm,
                cache_dir=crop_cache_dir,
                expansion=0.0,
            )
        except (FileNotFoundError, OSError, ValueError) as exc:
            logger.debug(
                "neighbor page-image crop failed for page=%d bbox=%s: %s",
                neighbor.page,
                neighbor.bbox_norm,
                exc,
            )
    return None


async def _crop_context_window(
    packet: EvidencePacket,
    *,
    pdf_path: Path | None,
    page_image: Path | None,
    crop_cache_dir: Path | None,
    bbox: tuple[float, float, float, float] | None = None,
    pad: float = _RETRY_CONTEXT_WINDOW_PAD,
) -> str | None:
    """Render a wider crop around the packet bbox for verifier retries."""
    bbox = bbox or _context_window_bbox(packet, pad=pad)
    if bbox is None:
        return None
    if pdf_path is not None:
        try:
            out = await inspect_region(
                InspectRegionInput(
                    doc_path=str(pdf_path),
                    page=packet.page,
                    bbox_norm=bbox,
                    mode="image",
                    expansion="none",
                ),
                cache_dir=crop_cache_dir,
            )
            return out.crop_ref
        except (FileNotFoundError, ValueError) as exc:
            logger.debug(
                "context-window crop failed for packet=%s page=%d bbox=%s: %s",
                packet.packet_id,
                packet.page,
                bbox,
                exc,
            )

    if page_image is not None:
        try:
            return _crop_page_image(
                page_image,
                bbox,
                cache_dir=crop_cache_dir,
                expansion=0.0,
            )
        except (FileNotFoundError, OSError, ValueError) as exc:
            logger.debug(
                "context-window page-image crop failed for packet=%s page=%d bbox=%s: %s",
                packet.packet_id,
                packet.page,
                bbox,
                exc,
            )
    return None


def _context_window_bbox(
    packet: EvidencePacket,
    *,
    pad: float = _RETRY_CONTEXT_WINDOW_PAD,
) -> tuple[float, float, float, float] | None:
    bbox = _pad_bbox(packet.bbox_norm, pad=pad)
    if _bbox_equal(bbox, packet.bbox_norm):
        return None
    return bbox


def _synth_context_window_region(
    packet: EvidencePacket,
    bbox: tuple[float, float, float, float],
) -> RegionCandidate:
    return RegionCandidate(
        region_id=f"{packet.packet_id}_context_window",
        page=packet.page,
        bbox_norm=bbox,
        region_type=packet.region_type or "context_window",
        score=float(packet.confidence),
    )


async def _extract_neighbor_text(
    neighbor: RegionCandidate,
    *,
    role: str,
    pdf_path: Path | None,
    crop_ref: str | None,
    text_layer_cache_dir: Path | None,
    crop_cache_dir: Path | None,
) -> str | None:
    """Best-effort text snippet for an attached neighbor.

    The reasoner sees linked neighbor images, but the verifier and packet
    descriptor are text-first. Pull native text where possible; fall back to
    OCR so captions/footnotes/legend labels do not disappear from those
    compact summaries.
    """
    if pdf_path is not None:
        try:
            text_out = await get_text_layer(
                GetTextLayerInput(
                    doc_path=str(pdf_path),
                    page=neighbor.page,
                    bbox_norm=neighbor.bbox_norm,
                ),
                cache_dir=text_layer_cache_dir,
            )
            text = _clean_context_text(text_out.text)
            if text:
                return text
        except (FileNotFoundError, ValueError) as exc:
            logger.debug(
                "neighbor text layer failed for role=%s page=%d bbox=%s: %s",
                role,
                neighbor.page,
                neighbor.bbox_norm,
                exc,
            )

        try:
            ocr_out = await inspect_region(
                InspectRegionInput(
                    doc_path=str(pdf_path),
                    page=neighbor.page,
                    bbox_norm=neighbor.bbox_norm,
                    mode="element",
                    expansion="none",
                ),
                cache_dir=crop_cache_dir,
            )
            return _clean_context_text(ocr_out.ocr_text)
        except (FileNotFoundError, ValueError) as exc:
            logger.debug(
                "neighbor OCR failed for role=%s page=%d bbox=%s: %s",
                role,
                neighbor.page,
                neighbor.bbox_norm,
                exc,
            )
            return None

    if crop_ref:
        text, _confidence = _ocr_existing_crop(Path(crop_ref))
        return _clean_context_text(text)
    return None


def _context_text_updates(
    packet: EvidencePacket, linked_texts: list[tuple[str, str]]
) -> dict[str, str]:
    """Append linked-neighbor snippets to whichever packet text field is visible."""
    if not linked_texts:
        return {}

    seen_text_keys = _existing_context_text_keys(packet)
    context_lines: list[str] = []
    for role, text in linked_texts:
        cleaned = text.strip()
        if not cleaned:
            continue
        key = _context_text_key(cleaned)
        if key in seen_text_keys:
            continue
        seen_text_keys.add(key)
        context_lines.append(f"Context [{role}]: {cleaned}")
    if not context_lines:
        return {}
    context = "\n".join(context_lines)
    if packet.text_layer_snippet:
        return {"text_layer_snippet": f"{packet.text_layer_snippet.rstrip()}\n{context}"}
    if packet.ocr_snippet:
        return {"ocr_snippet": f"{packet.ocr_snippet.rstrip()}\n{context}"}
    return {"text_layer_snippet": context}


def _existing_context_text_keys(packet: EvidencePacket) -> set[str]:
    """Return normalized context snippets already attached to a packet."""
    keys: set[str] = set()
    for snippet in (packet.text_layer_snippet, packet.ocr_snippet):
        for line in (snippet or "").splitlines():
            match = _CONTEXT_LINE_RE.match(line.strip())
            if match:
                keys.add(_context_text_key(match.group("text")))
    return keys


def _context_text_key(text: str) -> str:
    return " ".join(text.split()).casefold()


def _clean_context_text(text: str | None) -> str | None:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return None
    if len(cleaned) <= _MAX_LINKED_CONTEXT_TEXT_CHARS:
        return cleaned
    return cleaned[: _MAX_LINKED_CONTEXT_TEXT_CHARS - 3].rstrip() + "..."


def _figure_refs_from_text(*texts: str | None) -> set[str]:
    """Return figure numbers mentioned in packet or neighbor text."""
    refs: set[str] = set()
    for text in texts:
        for match in _FIGURE_REF_RE.finditer(text or ""):
            refs.add(match.group("num").lower())
    return refs


def _neighbor_text_mismatches_packet_figure(
    packet_figure_refs: set[str],
    *,
    role: str,
    linked_text: str,
) -> bool:
    """Drop obviously wrong figure captions from chart/image packets.

    Dense chart pages often have several adjacent captions. If a primary
    packet OCR says "Figure 31" and a candidate caption says only "Figure 33",
    attaching that caption gives the reasoner conflicting context. We only
    filter caption-like neighbors and only when both sides contain figure refs.
    """
    role_key = (role or "").lower()
    if "caption" not in role_key or not packet_figure_refs:
        return False
    neighbor_refs = _figure_refs_from_text(linked_text)
    return bool(neighbor_refs) and packet_figure_refs.isdisjoint(neighbor_refs)


# ---------------------------------------------------------------------------
# Provenance annotation
# ---------------------------------------------------------------------------


def _updated_provenance(
    prev: PacketProvenance,
    n_neighbors: int,
    *,
    tag: str | None = None,
) -> PacketProvenance:
    """Stamp that expand_context contributed N neighbors to this packet.

    We keep the original `tool` + `mode` (the inspector owns those) and
    encode the expansion as a suffix in `args_hash` so trace readers can
    tell whether a packet was expanded without a dedicated field.
    """
    expand_tag = tag or f"expand_context:n{n_neighbors}"
    merged = (prev.args_hash + "|" + expand_tag) if prev.args_hash else expand_tag
    return PacketProvenance(
        tool=prev.tool,
        mode=prev.mode,
        args_hash=merged,
        tokens_used=prev.tokens_used,
        latency_ms=prev.latency_ms,
    )
