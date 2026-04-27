"""Typed evidence graph for the EXPAND_CONTEXT stage (Phase 2 item 5).

Sub-phase 2h gave us spatial-overlap-with-padded-bbox neighbor attachment —
catches captions just below figures, headers just above tables, etc. That
heuristic worked but treated every region the same way: any annotation-type
region within 8% of the bbox got the same score regardless of role.

This module encodes domain knowledge:

  * **Charts** want caption + footnote BELOW + title/section_header ABOVE.
    Bar/line charts especially want axis-style neighbors.
  * **Tables** want column-header / section-header ABOVE + footnote /
    caption BELOW.
  * **Generic figures** want caption + footnote BELOW + section_header
    ABOVE.
  * **Text + list-items** want section_header ABOVE.

The graph is keyed on `(region_type, figure_class)` with a `figure_class=None`
fallback. Each `NeighborSpec` has a target region_type, a directional
constraint (above / below / left / right / nearby), and a semantic role
(`title`, `caption`, `footnote`, etc.) so traces show WHY a neighbor was
attached, not just THAT it was.

The walker plays nicely with item 4's reranker: when the rerank populated
`RegionCandidate.expansion_hints` with `missing_context` strings (`legend`,
`caption`, `y_axis`, ...), the walker boosts neighbors whose role or
target_type appears in the hints. So the inspector's "I need a legend
to read this chart" intent flows from rerank → graph → linked_neighbor_types.

Fallback: when the graph has no entry for a region's type, the expander's
spatial-overlap heuristic still runs (so unknown / new region types from
future RT-DETRv2 versions don't silently lose neighbors).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from focusparse.pipeline.events import RegionCandidate

Direction = Literal["above", "below", "left", "right", "nearby"]


class NeighborSpec(BaseModel):
    """One row of the typed graph: 'this primary region wants a <target_type>
    in the <direction> direction, playing the <role> role.'"""

    target_type: str  # region_type the localizer might emit
    direction: Direction
    role: str  # 'title' | 'caption' | 'footnote' | 'legend' | 'axis' | ...


# Region-type vocabulary we expect from RT-DETRv2 (keyed by lowercased
# `region_type`, with `-` and `_` both supported on the key side).
# `figure_class=None` means "any figure_class for this region_type".
_GRAPH: dict[tuple[str, str | None], list[NeighborSpec]] = {
    # --- charts: titles above, captions/footnotes below ---
    ("picture", "bar_chart"): [
        NeighborSpec(target_type="caption", direction="below", role="caption"),
        NeighborSpec(target_type="footnote", direction="below", role="footnote"),
        NeighborSpec(target_type="title", direction="above", role="title"),
        NeighborSpec(target_type="section_header", direction="above", role="title"),
        NeighborSpec(target_type="section-header", direction="above", role="title"),
    ],
    ("picture", "line_chart"): [
        NeighborSpec(target_type="caption", direction="below", role="caption"),
        NeighborSpec(target_type="footnote", direction="below", role="footnote"),
        NeighborSpec(target_type="title", direction="above", role="title"),
        NeighborSpec(target_type="section_header", direction="above", role="title"),
        NeighborSpec(target_type="section-header", direction="above", role="title"),
    ],
    ("picture", "pie_chart"): [
        NeighborSpec(target_type="caption", direction="below", role="caption"),
        NeighborSpec(target_type="footnote", direction="below", role="footnote"),
        NeighborSpec(target_type="title", direction="above", role="title"),
        NeighborSpec(target_type="section_header", direction="above", role="title"),
        NeighborSpec(target_type="section-header", direction="above", role="title"),
    ],
    ("picture", "scatter_plot"): [
        NeighborSpec(target_type="caption", direction="below", role="caption"),
        NeighborSpec(target_type="footnote", direction="below", role="footnote"),
        NeighborSpec(target_type="section_header", direction="above", role="title"),
    ],
    # Generic picture (or unknown figure_class): just caption + footnote +
    # section_header. Logo / decorative pictures are unlikely to attract
    # meaningful neighbors anyway.
    ("picture", None): [
        NeighborSpec(target_type="caption", direction="below", role="caption"),
        NeighborSpec(target_type="footnote", direction="below", role="footnote"),
        NeighborSpec(target_type="section_header", direction="above", role="title"),
        NeighborSpec(target_type="section-header", direction="above", role="title"),
    ],
    # --- tables: header above, footnote below ---
    ("table", None): [
        NeighborSpec(target_type="section_header", direction="above", role="title"),
        NeighborSpec(target_type="section-header", direction="above", role="title"),
        NeighborSpec(target_type="title", direction="above", role="title"),
        NeighborSpec(target_type="footnote", direction="below", role="footnote"),
        NeighborSpec(target_type="caption", direction="below", role="caption"),
    ],
    # --- text / list / formula: just section header above ---
    ("text", None): [
        NeighborSpec(target_type="section_header", direction="above", role="title"),
        NeighborSpec(target_type="section-header", direction="above", role="title"),
    ],
    ("list-item", None): [
        NeighborSpec(target_type="section_header", direction="above", role="title"),
        NeighborSpec(target_type="section-header", direction="above", role="title"),
    ],
    ("list_item", None): [
        NeighborSpec(target_type="section_header", direction="above", role="title"),
        NeighborSpec(target_type="section-header", direction="above", role="title"),
    ],
    ("formula", None): [
        NeighborSpec(target_type="section_header", direction="above", role="title"),
        NeighborSpec(target_type="caption", direction="below", role="caption"),
    ],
}

# Boost factor for neighbors whose role/target_type matches the rerank's
# `expansion_hints`. Same multiplicative pattern used by the inspector's
# evidence-type boost (1.5×) — small enough that detector confidence
# still matters, large enough to flip ranking when the rerank had a
# strong opinion.
_HINT_BOOST = 1.5


def lookup(region_type: str | None, figure_class: str | None) -> list[NeighborSpec]:
    """Return the most specific graph entry for the (type, class) pair.

    Lookup order:
      1. (region_type, figure_class) — most specific
      2. (region_type, None)         — type-only fallback
      3. []                          — unknown type → caller falls back to
                                       spatial-overlap heuristic
    """
    if not region_type:
        return []
    rt = region_type.lower()
    fc = figure_class.lower() if figure_class else None
    if (rt, fc) in _GRAPH:
        return _GRAPH[(rt, fc)]
    if (rt, None) in _GRAPH:
        return _GRAPH[(rt, None)]
    return []


def extract_figure_class(region: RegionCandidate) -> str | None:
    """Pull `figure_class` out of `supporting_signals` if the localizer
    stamped it (i.e. for `picture` regions with a known sub-class)."""
    for s in region.supporting_signals:
        if s.startswith("figure_class="):
            return s.split("=", 1)[1] or None
    return None


# ---------------------------------------------------------------------------
# Spatial-direction predicates
# ---------------------------------------------------------------------------


def matches_direction(
    candidate: RegionCandidate,
    primary: tuple[float, float, float, float],
    direction: Direction,
    *,
    max_distance: float = 0.25,
    min_overlap_fraction: float = 0.20,
) -> bool:
    """True iff `candidate` is in the requested direction relative to `primary`.

    Direction semantics (in normalized [0,1] page space):

      * `above` — candidate centroid_y < primary centroid_y; vertical gap
        ≤ max_distance; horizontal extent overlaps primary by ≥
        min_overlap_fraction (so a section-header on the OTHER column
        doesn't count).
      * `below` — symmetric; candidate below primary.
      * `left`  — candidate to the left in the same row band.
      * `right` — symmetric; candidate to the right.
      * `nearby` — any direction; falls back to bbox-overlap-with-padding
        which the expander already does.

    Tunables match the existing 8% adjacency_pad scale; max_distance is
    deliberately wider (25%) so a footnote at the bottom of the page can
    still match a chart in the upper half.
    """
    cx0, cy0, cx1, cy1 = candidate.bbox_norm
    px0, py0, px1, py1 = primary
    c_cx = (cx0 + cx1) / 2.0
    c_cy = (cy0 + cy1) / 2.0
    p_cx = (px0 + px1) / 2.0
    p_cy = (py0 + py1) / 2.0

    if direction == "above":
        if c_cy >= p_cy:
            return False
        gap = p_cy - c_cy
        if gap > max_distance:
            return False
        return _horizontal_overlap_fraction(candidate.bbox_norm, primary) >= min_overlap_fraction

    if direction == "below":
        if c_cy <= p_cy:
            return False
        gap = c_cy - p_cy
        if gap > max_distance:
            return False
        return _horizontal_overlap_fraction(candidate.bbox_norm, primary) >= min_overlap_fraction

    if direction == "left":
        if c_cx >= p_cx:
            return False
        gap = p_cx - c_cx
        if gap > max_distance:
            return False
        return _vertical_overlap_fraction(candidate.bbox_norm, primary) >= min_overlap_fraction

    if direction == "right":
        if c_cx <= p_cx:
            return False
        gap = c_cx - p_cx
        if gap > max_distance:
            return False
        return _vertical_overlap_fraction(candidate.bbox_norm, primary) >= min_overlap_fraction

    if direction == "nearby":
        # Permissive: any spatial proximity within 1.5× max_distance on
        # both axes. Used as a final-fallback rule for unknown
        # directions.
        return abs(c_cx - p_cx) <= 1.5 * max_distance and abs(c_cy - p_cy) <= 1.5 * max_distance

    return False


def _horizontal_overlap_fraction(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> float:
    """Overlap-on-x as a fraction of the smaller bbox's width.

    Smaller-of-the-two so a tiny caption inside a wide figure's column
    band counts as fully overlapping (overlap / caption_width = 1.0).
    """
    a0, _, a1, _ = a
    b0, _, b1, _ = b
    overlap = max(0.0, min(a1, b1) - max(a0, b0))
    smaller = min(a1 - a0, b1 - b0)
    if smaller <= 0:
        return 0.0
    return overlap / smaller


def _vertical_overlap_fraction(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> float:
    _, a0, _, a1 = a
    _, b0, _, b1 = b
    overlap = max(0.0, min(a1, b1) - max(a0, b0))
    smaller = min(a1 - a0, b1 - b0)
    if smaller <= 0:
        return 0.0
    return overlap / smaller


# ---------------------------------------------------------------------------
# Graph walker
# ---------------------------------------------------------------------------


def find_graph_neighbors(
    primary_region: RegionCandidate,
    candidates: list[RegionCandidate],
    *,
    expansion_hints: list[str] | None = None,
) -> list[tuple[RegionCandidate, str]]:
    """Walk the graph for `primary_region` and return matched neighbors.

    Returns a list of `(neighbor, role)` tuples ordered by score (highest
    first). Each rule contributes at most one neighbor — the best match
    in the requested direction. When two neighbors tie on score, the one
    whose role appears in `expansion_hints` wins.

    `expansion_hints` is the rerank's `missing_context` taxonomy
    (`legend`, `caption`, `y_axis`, ...) carried on `RegionCandidate
    .expansion_hints`. We treat hint membership as a 1.5× score boost
    so the rerank's "I need this kind of context" signal flows through.
    """
    figure_class = extract_figure_class(primary_region)
    rules = lookup(primary_region.region_type, figure_class)
    if not rules:
        return []

    hints = {h.lower() for h in (expansion_hints or [])}
    primary_bbox = primary_region.bbox_norm

    found: list[tuple[float, RegionCandidate, str]] = []
    seen_ids: set[str] = set()
    for rule in rules:
        rule_target = rule.target_type.lower()
        best: tuple[float, RegionCandidate] | None = None
        for cand in candidates:
            if cand.region_id == primary_region.region_id:
                continue
            if cand.region_id in seen_ids:
                continue
            ctype = (cand.region_type or "").lower()
            if ctype != rule_target:
                continue
            if not matches_direction(cand, primary_bbox, rule.direction):
                continue
            score = float(cand.score)
            # Boost neighbors that match a hint from the rerank.
            if rule.role.lower() in hints or rule_target in hints:
                score *= _HINT_BOOST
            if best is None or score > best[0]:
                best = (score, cand)
        if best is not None:
            found.append((best[0], best[1], rule.role))
            seen_ids.add(best[1].region_id)

    found.sort(key=lambda t: -t[0])
    return [(cand, role) for _score, cand, role in found]


def has_graph_entry(region_type: str | None, figure_class: str | None = None) -> bool:
    """Check whether the graph has any rule for this primary type.

    Useful for the expander to decide: graph walker first when an entry
    exists, otherwise fall back to spatial-overlap heuristic.
    """
    return bool(lookup(region_type, figure_class))
