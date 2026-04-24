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
from focusparse.pipeline.events import EvidenceEvent, RegionCandidate, RegionsEvent
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

_DEFAULT_MAX_NEIGHBORS_PER_PACKET = 4
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
            compact).
        adjacency_pad: fractional bbox expansion for the overlap test.

    Returns:
        An `EvidenceEvent` with the same packets, each potentially carrying
        `linked_crop_refs` / `linked_neighbor_types` / updated provenance.
    """
    if regions is None or pdf_path is None:
        return evidence

    # Group regions by page so the per-packet lookup is O(regions_on_page),
    # not O(total_regions). For long docs this matters.
    regions_by_page: dict[int, list[RegionCandidate]] = {}
    for r in regions.candidates:
        regions_by_page.setdefault(r.page, []).append(r)

    new_packets: list[EvidencePacket] = []
    for packet in evidence.packets:
        candidates_on_page = regions_by_page.get(packet.page, [])
        neighbors = _pick_neighbors(
            packet,
            candidates_on_page,
            max_n=max_neighbors_per_packet,
            pad=adjacency_pad,
        )
        if not neighbors:
            new_packets.append(packet)
            continue

        linked_refs: list[str] = []
        linked_types: list[str] = []
        for neighbor in neighbors:
            crop_ref = await _crop_neighbor(
                neighbor,
                pdf_path=pdf_path,
                crop_cache_dir=crop_cache_dir,
            )
            if crop_ref is None:
                continue
            linked_refs.append(crop_ref)
            linked_types.append((neighbor.region_type or "").lower() or "unknown")

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
) -> list[RegionCandidate]:
    """Return up to `max_n` annotation-type regions adjacent to `packet`.

    Selection:
      * region_type must be in `_NEIGHBOR_TYPES`
      * must not BE the packet region (same bbox / same region_id)
      * padded packet bbox must overlap the candidate bbox

    Ordering: we want the most relevant neighbors first when capping.
    "Most relevant" is approximated as (smaller distance, higher score);
    we sort by vertical distance to the packet center (captions below,
    headers above), breaking ties by detector score descending.
    """
    if not candidates:
        return []
    packet_bbox = _pad_bbox(packet.bbox_norm, pad=pad)
    px_center_y = (packet.bbox_norm[1] + packet.bbox_norm[3]) / 2.0

    matches: list[tuple[float, float, RegionCandidate]] = []
    for cand in candidates:
        ctype = (cand.region_type or "").lower()
        if ctype not in _NEIGHBOR_TYPES:
            continue
        if _bbox_equal(cand.bbox_norm, packet.bbox_norm):
            continue  # same region the packet already covers
        if not _bbox_overlaps(packet_bbox, cand.bbox_norm):
            continue
        cy = (cand.bbox_norm[1] + cand.bbox_norm[3]) / 2.0
        # Primary key: vertical distance (closer wins).
        # Secondary key: -score (higher detector confidence breaks ties).
        matches.append((abs(cy - px_center_y), -float(cand.score), cand))

    matches.sort(key=lambda t: (t[0], t[1]))
    return [cand for _d, _s, cand in matches[:max_n]]


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
