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

When `regions` or `pdf_path` is unavailable the stage returns evidence
unchanged — downstream stages get exactly the pre-2h passthrough
behavior, preserving every existing caller.
"""

from __future__ import annotations

import logging
from pathlib import Path

from focusparse.evidence.packet import EvidencePacket, PacketProvenance
from focusparse.pipeline.events import EvidenceEvent, PlanEvent, RegionCandidate, RegionsEvent
from focusparse.pipeline.evidence_graph import (
    extract_figure_class,
    find_graph_neighbors,
    has_graph_entry,
)
from focusparse.tools.inspect_region import InspectRegionInput, inspect_region

logger = logging.getLogger(__name__)

# Region types that annotate a nearby primary region. Intentionally tight —
# other pictures / text blocks are not "annotations", they're siblings.
_NEIGHBOR_TYPES: frozenset[str] = frozenset(
    {
        "caption",
        "footnote",
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
    "caption": frozenset({"caption"}),
    "footnote": frozenset({"footnote"}),
    "header": frozenset({"page-header", "section_header", "section-header", "title"}),
    "footer": frozenset({"page-footer"}),
    "title": frozenset({"title", "section_header", "section-header"}),
    "section_header": frozenset({"section_header", "section-header", "title"}),
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
# Expand the packet's bbox by this fraction of the [0,1] range on each side
# when testing for neighbor overlap. 0.08 ≈ ~1 inch on a Letter page at 300
# DPI — enough to catch a caption a few text lines away.
_DEFAULT_ADJACENCY_PAD = 0.08


async def expand_context(
    evidence: EvidenceEvent,
    *,
    regions: RegionsEvent | None = None,
    pdf_path: Path | None = None,
    crop_cache_dir: Path | None = None,
    max_neighbors_per_packet: int = _DEFAULT_MAX_NEIGHBORS_PER_PACKET,
    adjacency_pad: float = _DEFAULT_ADJACENCY_PAD,
    use_evidence_graph: bool = False,
    plan: PlanEvent | None = None,
    relevance_threshold: float = _DEFAULT_NEIGHBOR_RELEVANCE_THRESHOLD,
) -> EvidenceEvent:
    """Attach annotation neighbors to each packet, or pass through unchanged.

    Args:
        evidence: packets from the inspector.
        regions: full `RegionsEvent` from the localizer. When None, the
            stage is a passthrough — we need the full region list to find
            neighbors the inspector didn't promote to a packet.
        pdf_path: source PDF. Required for cropping neighbor regions;
            without it, the expander is a passthrough (we don't want to
            invent crop refs that point nowhere).
        crop_cache_dir: where neighbor crop PNGs go. Content-addressed by
            `inspect_region` so repeated calls on the same region are free.
        max_neighbors_per_packet: cap (plan §2e says 4 to keep packets
            compact). Halved automatically when neither `plan` nor the
            reranker provided a relevance signal (see
            `_FALLBACK_MAX_NEIGHBORS_PER_PACKET`).
        adjacency_pad: fractional bbox expansion for the overlap test.
        plan: optional `PlanEvent`. When provided, `plan.evidence_types`
            filters neighbor candidates to types the planner asked for
            (e.g. "caption" → only attach captions). Without `plan` and
            without reranker relevance scores, the expander falls back
            to a tighter spatial-only budget — the rebaseline-v2 finding
            (2026-05-05) showed that query-blind expansion attached ~13
            neighbors per example and hurt 11 of 13 affected examples.
        relevance_threshold: when the reranker (Phase 2 item 4) scored
            candidates, neighbors below this threshold are filtered out
            even if they overlap spatially. Default 0.3.

    Returns:
        An `EvidenceEvent` with the same packets, each potentially carrying
        `linked_crop_refs` / `linked_neighbor_types` / updated provenance.
    """
    if regions is None or pdf_path is None:
        return evidence

    # Resolve which neighbor region_types the planner permits. Empty set
    # means "no planner hint" → fall back to the conservative budget.
    permitted_neighbor_types = _resolve_permitted_neighbor_types(plan)
    has_planner_hint = bool(permitted_neighbor_types)
    has_rerank_signal = any(
        c.relevance is not None or c.needed_for is not None for c in regions.candidates
    )
    effective_max = (
        max_neighbors_per_packet
        if (has_planner_hint or has_rerank_signal)
        else _FALLBACK_MAX_NEIGHBORS_PER_PACKET
    )

    # Group regions by page so the per-packet lookup is O(regions_on_page),
    # not O(total_regions). For long docs this matters.
    regions_by_page: dict[int, list[RegionCandidate]] = {}
    for r in regions.candidates:
        regions_by_page.setdefault(r.page, []).append(r)

    new_packets: list[EvidencePacket] = []
    for packet in evidence.packets:
        candidates_on_page = regions_by_page.get(packet.page, [])
        # Find the matching RegionCandidate so we can read figure_class +
        # expansion_hints (populated by item 4's reranker).
        primary_region = _match_primary_region(packet, candidates_on_page)

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
        if use_evidence_graph and has_graph_entry(packet.region_type, figure_class):
            hints = primary_region.expansion_hints if primary_region else None
            graph_matches = find_graph_neighbors(
                primary_region or _synth_primary_from_packet(packet),
                candidates_on_page,
                expansion_hints=hints,
            )[:max_neighbors_per_packet]

        if graph_matches:
            neighbors_with_role: list[tuple[RegionCandidate, str]] = list(graph_matches)
        else:
            # Fallback: spatial-overlap heuristic, but query-aware (filter
            # by planner evidence_types and/or reranker relevance/needed_for).
            spatial = _pick_neighbors(
                packet,
                candidates_on_page,
                max_n=effective_max,
                pad=adjacency_pad,
                permitted_neighbor_types=permitted_neighbor_types,
                has_planner_hint=has_planner_hint,
                relevance_threshold=relevance_threshold,
            )
            neighbors_with_role = [(n, (n.region_type or "").lower() or "unknown") for n in spatial]

        if not neighbors_with_role:
            new_packets.append(packet)
            continue

        linked_refs: list[str] = []
        linked_types: list[str] = []
        for neighbor, role in neighbors_with_role:
            crop_ref = await _crop_neighbor(
                neighbor,
                pdf_path=pdf_path,
                crop_cache_dir=crop_cache_dir,
            )
            if crop_ref is None:
                continue
            linked_refs.append(crop_ref)
            # Use the graph's semantic role (caption / title / footnote /
            # legend / axis) when present; falls back to the raw region_type
            # for spatial-heuristic matches.
            linked_types.append(role)

        if not linked_refs:
            new_packets.append(packet)
            continue

        new_packets.append(
            packet.model_copy(
                update={
                    "linked_crop_refs": linked_refs,
                    "linked_neighbor_types": linked_types,
                    "provenance": _updated_provenance(packet.provenance, len(linked_refs)),
                }
            )
        )
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
    """Return up to `max_n` annotation-type regions adjacent to `packet`.

    Selection (query-aware as of 2026-05-05):
      * region_type must be in `_NEIGHBOR_TYPES`
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
        if ctype not in _NEIGHBOR_TYPES:
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


def _resolve_permitted_neighbor_types(plan: PlanEvent | None) -> frozenset[str]:
    """Map `plan.evidence_types` (planner vocab) to the set of detector-vocab
    region_types the expander is allowed to attach as neighbors.

    Returns an empty set when `plan` is None or `evidence_types` is empty;
    callers fall back to the legacy spatial heuristic in that case (with a
    tighter neighbor cap to bound noise).
    """
    if plan is None or not plan.evidence_types:
        return frozenset()
    permitted: set[str] = set()
    for raw in plan.evidence_types:
        key = (raw or "").strip().lower()
        if not key:
            continue
        aliases = _EVIDENCE_TYPE_TO_NEIGHBOR_TYPES.get(key)
        if aliases:
            permitted |= aliases
    return frozenset(permitted)


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
    pdf_path: Path,
    crop_cache_dir: Path | None,
) -> str | None:
    """Render a cropped PNG for a neighbor region; return None on failure."""
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
        return None


# ---------------------------------------------------------------------------
# Provenance annotation
# ---------------------------------------------------------------------------


def _updated_provenance(prev: PacketProvenance, n_neighbors: int) -> PacketProvenance:
    """Stamp that expand_context contributed N neighbors to this packet.

    We keep the original `tool` + `mode` (the inspector owns those) and
    encode the expansion as a suffix in `args_hash` so trace readers can
    tell whether a packet was expanded without a dedicated field.
    """
    expand_tag = f"expand_context:n{n_neighbors}"
    merged = (prev.args_hash + "|" + expand_tag) if prev.args_hash else expand_tag
    return PacketProvenance(
        tool=prev.tool,
        mode=prev.mode,
        args_hash=merged,
        tokens_used=prev.tokens_used,
        latency_ms=prev.latency_ms,
    )
