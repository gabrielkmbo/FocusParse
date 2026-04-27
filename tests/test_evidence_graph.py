"""Tests for `focusparse.pipeline.evidence_graph` (Phase 2 item 5).

Pure-function tests — no I/O, no LLM, no PyMuPDF. Covers:
  * graph lookup: most-specific match, fallback to figure_class=None,
    empty list for unknown types
  * `extract_figure_class` reads the localizer's signal format
  * directional predicates (above / below / left / right / nearby) with
    horizontal/vertical-overlap requirements
  * graph walker selects best candidate per rule, dedupes across rules
  * `expansion_hints` from item 4's reranker boosts matching neighbors
"""

from __future__ import annotations

import pytest

from focusparse.pipeline.events import RegionCandidate
from focusparse.pipeline.evidence_graph import (
    NeighborSpec,
    extract_figure_class,
    find_graph_neighbors,
    has_graph_entry,
    lookup,
    matches_direction,
)


def _r(
    region_id: str,
    *,
    bbox: tuple[float, float, float, float],
    region_type: str,
    score: float = 0.7,
    page: int = 1,
    figure_class: str | None = None,
    expansion_hints: list[str] | None = None,
) -> RegionCandidate:
    signals = []
    if figure_class:
        signals.append(f"figure_class={figure_class}")
    return RegionCandidate(
        region_id=region_id,
        page=page,
        bbox_norm=bbox,
        region_type=region_type,
        score=score,
        supporting_signals=signals,
        expansion_hints=expansion_hints or [],
    )


# ---------------------------------------------------------------------------
# lookup() / has_graph_entry()
# ---------------------------------------------------------------------------


def test_lookup_returns_specific_entry_for_chart_subclass():
    rules = lookup("picture", "bar_chart")
    assert rules
    # Bar charts get caption + footnote + title rules.
    targets = {r.target_type for r in rules}
    assert "caption" in targets
    assert "footnote" in targets


def test_lookup_falls_back_to_figure_class_none_for_unknown_subclass():
    """`logo` isn't in the graph; should fall through to the generic
    picture rules."""
    rules = lookup("picture", "logo")
    assert rules
    targets = {r.target_type for r in rules}
    # Generic picture rules: caption + footnote + section_header
    assert "caption" in targets


def test_lookup_returns_empty_for_unknown_region_type():
    """No entry for `page-header` as a primary → empty rules."""
    assert lookup("page-header", None) == []


def test_lookup_handles_case_insensitive_region_type():
    """RT-DETRv2 sometimes emits `Picture` instead of `picture`."""
    rules = lookup("Picture", None)
    assert rules


def test_has_graph_entry():
    assert has_graph_entry("picture") is True
    assert has_graph_entry("table") is True
    assert has_graph_entry("text") is True
    assert has_graph_entry("page-header") is False
    assert has_graph_entry(None) is False


# ---------------------------------------------------------------------------
# extract_figure_class
# ---------------------------------------------------------------------------


def test_extract_figure_class_reads_supporting_signal():
    region = _r(
        "r1",
        bbox=(0.1, 0.1, 0.5, 0.5),
        region_type="picture",
        figure_class="bar_chart",
    )
    assert extract_figure_class(region) == "bar_chart"


def test_extract_figure_class_returns_none_when_absent():
    region = _r("r1", bbox=(0.1, 0.1, 0.5, 0.5), region_type="text")
    assert extract_figure_class(region) is None


# ---------------------------------------------------------------------------
# matches_direction
# ---------------------------------------------------------------------------


def test_above_requires_candidate_above_with_horizontal_overlap():
    primary = (0.1, 0.4, 0.9, 0.6)  # wide band middle of page
    above_aligned = _r("a", bbox=(0.2, 0.30, 0.8, 0.36), region_type="title")
    above_offset = _r("b", bbox=(0.0, 0.30, 0.05, 0.36), region_type="title")
    below = _r("c", bbox=(0.2, 0.70, 0.8, 0.76), region_type="title")
    far_above = _r("d", bbox=(0.2, 0.05, 0.8, 0.10), region_type="title")

    assert matches_direction(above_aligned, primary, "above")
    # Off to the side → no horizontal overlap → fails
    assert not matches_direction(above_offset, primary, "above")
    # Below the primary → fails the y-direction check
    assert not matches_direction(below, primary, "above")
    # Far above (gap > 0.25) → distance limit kicks in
    assert not matches_direction(far_above, primary, "above")


def test_below_is_symmetric_to_above():
    primary = (0.1, 0.4, 0.9, 0.5)
    caption = _r("c", bbox=(0.2, 0.55, 0.8, 0.60), region_type="caption")
    above = _r("a", bbox=(0.2, 0.30, 0.8, 0.36), region_type="caption")

    assert matches_direction(caption, primary, "below")
    assert not matches_direction(above, primary, "below")


def test_left_requires_vertical_overlap():
    """A legend to the left of a chart should sit in the same y-band.

    Distance is measured center-to-center, so the legend has to be close
    enough that its centroid is within 0.25 of the chart's centroid.
    """
    # Chart on the right half of the page; legend just to its left.
    chart = (0.45, 0.3, 0.85, 0.7)
    # Legend center x = 0.41 → gap from chart center (0.65) = 0.24, within
    # the 0.25 max_distance window.
    legend_aligned = _r("l", bbox=(0.36, 0.4, 0.46, 0.6), region_type="picture")
    legend_off = _r("o", bbox=(0.36, 0.05, 0.46, 0.10), region_type="picture")

    assert matches_direction(legend_aligned, chart, "left")
    assert not matches_direction(legend_off, chart, "left")


def test_nearby_is_permissive():
    primary = (0.4, 0.4, 0.6, 0.6)
    close = _r("c", bbox=(0.30, 0.30, 0.45, 0.45), region_type="caption")
    far = _r("f", bbox=(0.0, 0.0, 0.05, 0.05), region_type="caption")

    assert matches_direction(close, primary, "nearby")
    assert not matches_direction(far, primary, "nearby")


# ---------------------------------------------------------------------------
# find_graph_neighbors
# ---------------------------------------------------------------------------


def test_find_neighbors_for_chart_picks_best_candidate_per_rule():
    """A bar_chart should attract a caption (below) + a section_header
    (above). The walker picks the highest-scoring candidate per rule."""
    # Chart in the upper half so caption candidates fit within the 0.25
    # max_distance window.
    chart = _r(
        "chart",
        bbox=(0.1, 0.25, 0.9, 0.55),
        region_type="picture",
        figure_class="bar_chart",
        score=0.9,
    )
    candidates = [
        chart,
        # Two caption candidates, both within the 0.25 max_distance window
        # (chart centroid_y = 0.40; both centroid_y ≤ 0.65). Higher score wins.
        _r("cap_a", bbox=(0.2, 0.56, 0.8, 0.60), region_type="caption", score=0.6),
        _r("cap_b", bbox=(0.2, 0.60, 0.8, 0.64), region_type="caption", score=0.8),
        _r("hdr", bbox=(0.2, 0.16, 0.8, 0.20), region_type="section_header", score=0.85),
        _r(
            "footer",
            bbox=(0.0, 0.95, 0.05, 0.99),
            region_type="page-footer",
            score=0.9,
        ),
    ]

    out = find_graph_neighbors(chart, candidates)
    role_by_neighbor = {n.region_id: role for n, role in out}
    # Picked the higher-confidence caption (cap_b at 0.8 > cap_a at 0.6).
    assert "cap_b" in role_by_neighbor
    assert role_by_neighbor["cap_b"] == "caption"
    # Section header above gets attached as 'title' role.
    assert "hdr" in role_by_neighbor
    assert role_by_neighbor["hdr"] == "title"
    # page-footer isn't a target of any chart rule → not attached.
    assert "footer" not in role_by_neighbor


def test_find_neighbors_skips_when_no_graph_entry_for_primary():
    """page-header isn't in the graph → walker returns []."""
    primary = _r(
        "ph",
        bbox=(0.1, 0.0, 0.9, 0.05),
        region_type="page-header",
        score=0.9,
    )
    candidates = [
        primary,
        _r(
            "header",
            bbox=(0.1, 0.10, 0.9, 0.15),
            region_type="section_header",
            score=0.85,
        ),
    ]
    assert find_graph_neighbors(primary, candidates) == []


def test_find_neighbors_dedupes_same_neighbor_across_rules():
    """If two rules would point at the same candidate (e.g. both
    section_header and section-header rules match the same region), only
    the first match counts."""
    primary = _r(
        "tbl",
        bbox=(0.1, 0.4, 0.9, 0.7),
        region_type="table",
        score=0.9,
    )
    # Header above the table — should match both `section_header` and
    # `section-header` rules, but only attach once.
    header = _r(
        "hdr",
        bbox=(0.2, 0.32, 0.8, 0.36),
        region_type="section_header",
        score=0.85,
    )
    candidates = [primary, header]
    out = find_graph_neighbors(primary, candidates)
    assert len(out) == 1
    assert out[0][0].region_id == "hdr"
    assert out[0][1] == "title"


def test_expansion_hints_boost_matching_neighbor():
    """Item 4 reranker stamped `expansion_hints=["caption"]` on the chart;
    when two candidates would otherwise tie, the one matching the hint
    wins through the 1.5× score boost."""
    chart = _r(
        "chart",
        bbox=(0.1, 0.3, 0.9, 0.65),
        region_type="picture",
        figure_class="line_chart",
        score=0.9,
    )
    cap = _r("cap", bbox=(0.2, 0.68, 0.8, 0.72), region_type="caption", score=0.5)
    hdr = _r("hdr", bbox=(0.2, 0.20, 0.8, 0.25), region_type="section_header", score=0.6)
    candidates = [chart, cap, hdr]

    # No hints: header (0.6) outscores caption (0.5) on the title rule —
    # caption is still attached on its own rule, but ordering is by score.
    out_no_hints = find_graph_neighbors(chart, candidates, expansion_hints=None)
    score_no_hints = {n.region_id: i for i, (n, _) in enumerate(out_no_hints)}

    # With hint=["caption"]: caption gets 0.5 × 1.5 = 0.75, beats header 0.6.
    out_with_hint = find_graph_neighbors(chart, candidates, expansion_hints=["caption"])
    score_with_hint = {n.region_id: i for i, (n, _) in enumerate(out_with_hint)}
    assert score_with_hint["cap"] < score_no_hints.get("cap", 99)


def test_walker_returns_empty_when_no_candidates_match_direction():
    """Chart on page bottom → no candidates ABOVE within max_distance.
    Walker still returns whatever rules CAN match."""
    chart = _r(
        "chart",
        bbox=(0.1, 0.85, 0.9, 0.95),
        region_type="picture",
        figure_class="bar_chart",
        score=0.9,
    )
    # Only a header at the very top — too far above the bottom-of-page chart.
    too_far_header = _r(
        "hdr",
        bbox=(0.1, 0.05, 0.9, 0.10),
        region_type="section_header",
        score=0.85,
    )
    out = find_graph_neighbors(chart, [chart, too_far_header])
    # No matches — nothing within max_distance of the chart.
    assert out == []


def test_walker_excludes_primary_from_candidates():
    """A region with the same id as the primary must not match itself."""
    region = _r(
        "self",
        bbox=(0.1, 0.4, 0.9, 0.6),
        region_type="picture",
        figure_class="bar_chart",
        score=0.9,
    )
    out = find_graph_neighbors(region, [region])
    assert out == []


@pytest.mark.parametrize(
    "primary_type,expected_target",
    [
        ("table", "section_header"),
        ("text", "section_header"),
        ("formula", "section_header"),
    ],
)
def test_other_primary_types_get_section_header_above(primary_type, expected_target):
    primary = _r(
        "p",
        bbox=(0.1, 0.4, 0.9, 0.6),
        region_type=primary_type,
        score=0.9,
    )
    header = _r(
        "h",
        bbox=(0.2, 0.30, 0.8, 0.36),
        region_type=expected_target,
        score=0.85,
    )
    out = find_graph_neighbors(primary, [primary, header])
    assert out
    assert out[0][0].region_id == "h"


def test_neighbor_spec_is_pydantic_validatable():
    """Sanity check that NeighborSpec round-trips through pydantic."""
    spec = NeighborSpec(target_type="caption", direction="below", role="caption")
    payload = spec.model_dump_json()
    rebuilt = NeighborSpec.model_validate_json(payload)
    assert rebuilt == spec
