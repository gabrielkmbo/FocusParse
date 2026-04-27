"""Tests for `focusparse.pipeline.expander.expand_context` (sub-phase 2h).

Covers the neighbor-attachment logic:
  * passthrough when `regions` or `pdf_path` is None
  * finds caption/footnote/section_header/title neighbors that overlap the
    padded packet bbox
  * ignores unrelated region types (text/picture) even if spatially adjacent
  * ignores the packet's own region (same bbox) in the candidate pool
  * caps at max_neighbors_per_packet
  * ranks neighbors by vertical distance (closer wins), tiebreaks on score
  * handles packets on different pages independently
  * provenance.args_hash gets an expand_context tag
  * inspect_region failures on a neighbor don't take down the run
  * pad controls adjacency: neighbors outside the padded bbox are rejected

Monkeypatches `inspect_region` so no PyMuPDF calls happen.
"""

from __future__ import annotations

from pathlib import Path

from focusparse.evidence.packet import EvidencePacket, PacketProvenance
from focusparse.pipeline.events import EvidenceEvent, RegionCandidate, RegionsEvent
from focusparse.pipeline.expander import expand_context


def _packet(
    *,
    packet_id: str,
    page: int,
    bbox_norm: tuple[float, float, float, float],
    region_type: str | None = None,
) -> EvidencePacket:
    return EvidencePacket(
        packet_id=packet_id,
        page=page,
        bbox_norm=bbox_norm,
        region_type=region_type,
        page_thumbnail_ref=f"/tmp/p{page}.png",
        local_crop_ref=f"/tmp/p{page}_crop.png",
        provenance=PacketProvenance(tool="test", args_hash="seed"),
    )


def _region(
    *,
    page: int,
    bbox_norm: tuple[float, float, float, float],
    region_type: str,
    score: float = 0.9,
) -> RegionCandidate:
    return RegionCandidate(
        region_id=f"r_{page}_{region_type}",
        page=page,
        bbox_norm=bbox_norm,
        region_type=region_type,
        score=score,
    )


class _FakeInspectOut:
    def __init__(self, crop_ref: str):
        self.crop_ref = crop_ref
        self.ocr_text = None
        self.confidence = 1.0


def _install_fake_inspect(monkeypatch, *, calls: list, should_fail: set | None = None):
    """Monkeypatch inspect_region. `should_fail` is a set of (page, bbox) tuples
    to simulate crop failures; others return a deterministic fake PNG path."""
    should_fail = should_fail or set()

    async def _fake(inp, *, cache_dir=None):
        calls.append(
            {
                "page": inp.page,
                "bbox_norm": inp.bbox_norm,
                "mode": inp.mode,
                "expansion": inp.expansion,
                "cache_dir": cache_dir,
            }
        )
        key = (inp.page, tuple(round(v, 4) for v in inp.bbox_norm))
        if key in should_fail:
            raise FileNotFoundError("simulated")
        return _FakeInspectOut(crop_ref=f"/crops/p{inp.page}_{inp.bbox_norm}_{inp.mode}.png")

    monkeypatch.setattr("focusparse.pipeline.expander.inspect_region", _fake)


# ---------------------------------------------------------------------------
# Passthrough paths
# ---------------------------------------------------------------------------


async def test_passthrough_when_no_regions():
    """Without a regions list, the expander can't find neighbors — no-op."""
    ev = EvidenceEvent(packets=[_packet(packet_id="p0", page=1, bbox_norm=(0, 0, 0.5, 0.5))])
    out = await expand_context(ev, regions=None, pdf_path=Path("/fake.pdf"))
    assert out.packets == ev.packets


async def test_passthrough_when_no_pdf_path():
    """Without a PDF, we can't crop neighbors — return evidence unchanged."""
    ev = EvidenceEvent(packets=[_packet(packet_id="p0", page=1, bbox_norm=(0, 0, 0.5, 0.5))])
    regions = RegionsEvent(
        candidates=[
            _region(page=1, bbox_norm=(0, 0.5, 0.5, 0.6), region_type="caption"),
        ]
    )
    out = await expand_context(ev, regions=regions, pdf_path=None)
    assert out.packets == ev.packets


# ---------------------------------------------------------------------------
# Neighbor selection
# ---------------------------------------------------------------------------


async def test_attaches_caption_below_figure(tmp_path, monkeypatch):
    calls: list = []
    _install_fake_inspect(monkeypatch, calls=calls)
    pdf = tmp_path / "doc.pdf"

    # Figure occupies the upper half; caption is a thin band right under it.
    figure = _packet(packet_id="p0", page=1, bbox_norm=(0.1, 0.1, 0.9, 0.4), region_type="picture")
    regions = RegionsEvent(
        candidates=[
            figure_r := _region(page=1, bbox_norm=(0.1, 0.1, 0.9, 0.4), region_type="picture"),
            _region(page=1, bbox_norm=(0.15, 0.42, 0.85, 0.48), region_type="caption"),
        ]
    )
    # pyflakes — keep the figure_r reference alive for clarity above.
    assert figure_r.region_type == "picture"

    out = await expand_context(
        EvidenceEvent(packets=[figure]),
        regions=regions,
        pdf_path=pdf,
    )
    packet = out.packets[0]
    assert len(packet.linked_crop_refs) == 1
    assert packet.linked_neighbor_types == ["caption"]
    # inspect_region was called exactly once with mode=image + no expansion.
    assert len(calls) == 1
    assert calls[0]["mode"] == "image"
    assert calls[0]["expansion"] == "none"


async def test_ignores_non_neighbor_region_types(tmp_path, monkeypatch):
    calls: list = []
    _install_fake_inspect(monkeypatch, calls=calls)
    figure = _packet(packet_id="p0", page=1, bbox_norm=(0.1, 0.1, 0.9, 0.4), region_type="picture")
    # Two regions spatially adjacent to the figure; neither is an annotation
    # type (picture + text), so both get rejected.
    regions = RegionsEvent(
        candidates=[
            _region(page=1, bbox_norm=(0.1, 0.42, 0.4, 0.48), region_type="picture"),
            _region(page=1, bbox_norm=(0.5, 0.42, 0.9, 0.48), region_type="text"),
        ]
    )
    out = await expand_context(
        EvidenceEvent(packets=[figure]),
        regions=regions,
        pdf_path=tmp_path / "doc.pdf",
    )
    assert out.packets[0].linked_crop_refs == []
    assert calls == []


async def test_ignores_the_packets_own_region(tmp_path, monkeypatch):
    """A region with the same bbox as the packet is the packet itself —
    don't attach it to itself (even if its region_type is 'caption')."""
    calls: list = []
    _install_fake_inspect(monkeypatch, calls=calls)
    caption_packet = _packet(
        packet_id="p0", page=1, bbox_norm=(0.1, 0.4, 0.9, 0.45), region_type="caption"
    )
    regions = RegionsEvent(
        candidates=[
            _region(page=1, bbox_norm=(0.1, 0.4, 0.9, 0.45), region_type="caption"),
            _region(page=1, bbox_norm=(0.15, 0.42, 0.85, 0.46), region_type="footnote"),
        ]
    )
    out = await expand_context(
        EvidenceEvent(packets=[caption_packet]),
        regions=regions,
        pdf_path=tmp_path / "doc.pdf",
    )
    # The own-region caption is skipped; only the footnote attaches.
    assert out.packets[0].linked_neighbor_types == ["footnote"]


async def test_ignores_neighbors_outside_padded_bbox(tmp_path, monkeypatch):
    """A caption on the opposite half of the page should not attach."""
    calls: list = []
    _install_fake_inspect(monkeypatch, calls=calls)
    figure = _packet(packet_id="p0", page=1, bbox_norm=(0.0, 0.0, 0.2, 0.2), region_type="picture")
    regions = RegionsEvent(
        candidates=[
            _region(page=1, bbox_norm=(0.8, 0.8, 1.0, 0.9), region_type="caption"),
        ]
    )
    out = await expand_context(
        EvidenceEvent(packets=[figure]),
        regions=regions,
        pdf_path=tmp_path / "doc.pdf",
        adjacency_pad=0.05,  # small pad → far neighbor rejected
    )
    assert out.packets[0].linked_crop_refs == []


# ---------------------------------------------------------------------------
# Ranking + cap
# ---------------------------------------------------------------------------


async def test_caps_at_max_neighbors_per_packet(tmp_path, monkeypatch):
    """The graph walker for `picture` (None figure_class) yields 3 distinct
    rule matches (caption + footnote + section_header). With max=2 the
    cap kicks in and we get 2."""
    calls: list = []
    _install_fake_inspect(monkeypatch, calls=calls)
    figure = _packet(packet_id="p0", page=1, bbox_norm=(0.1, 0.3, 0.9, 0.5), region_type="picture")
    regions = RegionsEvent(
        candidates=[
            _region(page=1, bbox_norm=(0.1, 0.51, 0.9, 0.54), region_type="caption"),
            _region(page=1, bbox_norm=(0.1, 0.27, 0.9, 0.29), region_type="section_header"),
            _region(page=1, bbox_norm=(0.1, 0.59, 0.9, 0.61), region_type="footnote"),
        ]
    )
    out = await expand_context(
        EvidenceEvent(packets=[figure]),
        regions=regions,
        pdf_path=tmp_path / "doc.pdf",
        max_neighbors_per_packet=2,
    )
    assert len(out.packets[0].linked_crop_refs) == 2


async def test_graph_picks_highest_scoring_candidate_per_rule(tmp_path, monkeypatch):
    """When two regions of the same target_type are in the requested
    direction, the graph walker picks the one with the higher detector
    score (not the spatially-closest). Within the rule, ties are broken
    by which appears first in the candidates list."""
    calls: list = []
    _install_fake_inspect(monkeypatch, calls=calls)
    figure = _packet(packet_id="p0", page=1, bbox_norm=(0.1, 0.3, 0.9, 0.5), region_type="picture")
    regions = RegionsEvent(
        candidates=[
            # Both captions are below + within distance window.
            # Lower-score caption appears first; the higher-score one
            # should still be picked.
            _region(
                page=1,
                bbox_norm=(0.1, 0.51, 0.9, 0.54),
                region_type="caption",
                score=0.40,
            ),
            _region(
                page=1,
                bbox_norm=(0.1, 0.56, 0.9, 0.59),
                region_type="caption",
                score=0.85,
            ),
        ]
    )
    out = await expand_context(
        EvidenceEvent(packets=[figure]),
        regions=regions,
        pdf_path=tmp_path / "doc.pdf",
        max_neighbors_per_packet=1,
    )
    assert len(out.packets[0].linked_crop_refs) == 1
    # The fake's crop_ref encodes the bbox; the higher-scored caption
    # has y0=0.56.
    assert "0.56" in out.packets[0].linked_crop_refs[0]


async def test_different_pages_are_independent(tmp_path, monkeypatch):
    calls: list = []
    _install_fake_inspect(monkeypatch, calls=calls)
    p1 = _packet(packet_id="p0", page=1, bbox_norm=(0.1, 0.3, 0.9, 0.5), region_type="picture")
    p2 = _packet(packet_id="p1", page=2, bbox_norm=(0.1, 0.3, 0.9, 0.5), region_type="picture")
    regions = RegionsEvent(
        candidates=[
            # Caption on page 1 → attaches to p1's packet
            _region(page=1, bbox_norm=(0.1, 0.52, 0.9, 0.55), region_type="caption"),
            # Caption on page 2 → attaches to p2's packet
            _region(page=2, bbox_norm=(0.1, 0.52, 0.9, 0.55), region_type="caption"),
            # Caption on page 3 → no packet on page 3, unused
            _region(page=3, bbox_norm=(0.1, 0.52, 0.9, 0.55), region_type="caption"),
        ]
    )
    out = await expand_context(
        EvidenceEvent(packets=[p1, p2]),
        regions=regions,
        pdf_path=tmp_path / "doc.pdf",
    )
    assert all(len(p.linked_crop_refs) == 1 for p in out.packets)
    # Each crop is distinct — no cross-page contamination.
    assert out.packets[0].linked_crop_refs[0] != out.packets[1].linked_crop_refs[0]


# ---------------------------------------------------------------------------
# Provenance + resilience
# ---------------------------------------------------------------------------


async def test_provenance_gets_expand_context_tag(tmp_path, monkeypatch):
    calls: list = []
    _install_fake_inspect(monkeypatch, calls=calls)
    figure = _packet(packet_id="p0", page=1, bbox_norm=(0.1, 0.3, 0.9, 0.5), region_type="picture")
    regions = RegionsEvent(
        candidates=[
            _region(page=1, bbox_norm=(0.1, 0.52, 0.9, 0.55), region_type="caption"),
            _region(page=1, bbox_norm=(0.1, 0.28, 0.9, 0.3), region_type="section_header"),
        ]
    )
    out = await expand_context(
        EvidenceEvent(packets=[figure]),
        regions=regions,
        pdf_path=tmp_path / "doc.pdf",
    )
    args_hash = out.packets[0].provenance.args_hash
    # Prior inspector tag is preserved + our stamp appended.
    assert "seed" in args_hash
    assert "expand_context:n2" in args_hash


async def test_crop_failure_on_one_neighbor_does_not_crash(tmp_path, monkeypatch):
    """If inspect_region raises for one neighbor, the others still attach."""
    failing_bbox = (0.1, 0.52, 0.9, 0.55)
    calls: list = []
    _install_fake_inspect(
        monkeypatch,
        calls=calls,
        should_fail={(1, failing_bbox)},
    )

    figure = _packet(packet_id="p0", page=1, bbox_norm=(0.1, 0.3, 0.9, 0.5), region_type="picture")
    regions = RegionsEvent(
        candidates=[
            _region(page=1, bbox_norm=failing_bbox, region_type="caption"),
            _region(page=1, bbox_norm=(0.1, 0.56, 0.9, 0.58), region_type="footnote"),
        ]
    )
    out = await expand_context(
        EvidenceEvent(packets=[figure]),
        regions=regions,
        pdf_path=tmp_path / "doc.pdf",
    )
    # Failed crop is skipped; footnote still attaches.
    assert out.packets[0].linked_neighbor_types == ["footnote"]


async def test_all_neighbor_crops_fail_leaves_packet_unchanged(tmp_path, monkeypatch):
    """When every neighbor crop fails, the packet passes through as-is
    (no empty linked_* lists stamped, no bogus provenance)."""
    calls: list = []
    bad = (0.1, 0.52, 0.9, 0.55)
    _install_fake_inspect(monkeypatch, calls=calls, should_fail={(1, bad)})

    figure = _packet(packet_id="p0", page=1, bbox_norm=(0.1, 0.3, 0.9, 0.5), region_type="picture")
    regions = RegionsEvent(candidates=[_region(page=1, bbox_norm=bad, region_type="caption")])
    out = await expand_context(
        EvidenceEvent(packets=[figure]),
        regions=regions,
        pdf_path=tmp_path / "doc.pdf",
    )
    # Passthrough — same packet identity, no neighbors, untouched provenance.
    assert out.packets[0].linked_crop_refs == []
    assert out.packets[0].provenance.args_hash == "seed"


# ---------------------------------------------------------------------------
# Cache forwarding
# ---------------------------------------------------------------------------


async def test_crop_cache_dir_forwarded_to_inspect_region(tmp_path, monkeypatch):
    calls: list = []
    _install_fake_inspect(monkeypatch, calls=calls)
    pdf = tmp_path / "doc.pdf"
    crop_dir = tmp_path / "crops"

    figure = _packet(packet_id="p0", page=1, bbox_norm=(0.1, 0.3, 0.9, 0.5), region_type="picture")
    regions = RegionsEvent(
        candidates=[_region(page=1, bbox_norm=(0.1, 0.52, 0.9, 0.55), region_type="caption")]
    )
    await expand_context(
        EvidenceEvent(packets=[figure]),
        regions=regions,
        pdf_path=pdf,
        crop_cache_dir=crop_dir,
    )
    assert calls[0]["cache_dir"] == crop_dir


# ---------------------------------------------------------------------------
# Backwards-compat with the pre-2h signature
# ---------------------------------------------------------------------------


async def test_legacy_single_arg_call_is_passthrough():
    """Pre-2h callers invoked expand_context(evidence) with no kwargs — must
    still return evidence unchanged (zero neighbors, no crash)."""
    ev = EvidenceEvent(packets=[_packet(packet_id="p0", page=1, bbox_norm=(0, 0, 1, 1))])
    out = await expand_context(ev)
    assert out.packets == ev.packets


# ---------------------------------------------------------------------------
# Graph-driven expansion (Phase 2 item 5)
# ---------------------------------------------------------------------------


async def test_graph_walker_attaches_typed_role_for_chart_caption(tmp_path, monkeypatch):
    """`linked_neighbor_types` should now carry the graph's role
    (`caption`) rather than the raw region_type."""
    calls: list = []
    _install_fake_inspect(monkeypatch, calls=calls)
    figure = _packet(
        packet_id="p0",
        page=1,
        bbox_norm=(0.1, 0.3, 0.9, 0.5),
        region_type="picture",
    )
    regions = RegionsEvent(
        candidates=[
            # The matching primary region (same bbox) — graph reads
            # figure_class from its supporting_signals.
            RegionCandidate(
                region_id="r_chart",
                page=1,
                bbox_norm=(0.1, 0.3, 0.9, 0.5),
                region_type="picture",
                score=0.9,
                supporting_signals=["figure_class=bar_chart"],
            ),
            _region(
                page=1,
                bbox_norm=(0.1, 0.55, 0.9, 0.58),
                region_type="caption",
                score=0.85,
            ),
        ]
    )
    out = await expand_context(
        EvidenceEvent(packets=[figure]),
        regions=regions,
        pdf_path=tmp_path / "doc.pdf",
    )
    # Graph rule says caption-below → role="caption", not the raw type.
    assert out.packets[0].linked_neighbor_types == ["caption"]


async def test_graph_walker_falls_back_to_spatial_for_unknown_primary(tmp_path, monkeypatch):
    """When primary's region_type isn't in the graph (e.g. `page-header`),
    the spatial-overlap heuristic still runs and attaches generic
    annotation neighbors."""
    calls: list = []
    _install_fake_inspect(monkeypatch, calls=calls)
    primary = _packet(
        packet_id="p0",
        page=1,
        bbox_norm=(0.1, 0.0, 0.9, 0.04),
        region_type="page-header",
    )
    regions = RegionsEvent(
        candidates=[
            # Caption nearby — won't match the (no) graph rules but the
            # spatial heuristic accepts it as an annotation type.
            _region(
                page=1,
                bbox_norm=(0.1, 0.05, 0.9, 0.08),
                region_type="caption",
                score=0.7,
            ),
        ]
    )
    out = await expand_context(
        EvidenceEvent(packets=[primary]),
        regions=regions,
        pdf_path=tmp_path / "doc.pdf",
    )
    # Spatial fallback uses raw region_type, not a graph role.
    assert out.packets[0].linked_neighbor_types == ["caption"]


async def test_graph_walker_uses_expansion_hints_from_reranker(tmp_path, monkeypatch):
    """Item 4's reranker stamps `expansion_hints` on the primary region.
    The graph walker boosts neighbors whose role matches a hint, so the
    hint can flip the pick when scores are otherwise close."""
    calls: list = []
    _install_fake_inspect(monkeypatch, calls=calls)
    figure = _packet(
        packet_id="p0",
        page=1,
        bbox_norm=(0.1, 0.3, 0.9, 0.5),
        region_type="picture",
    )
    primary_with_hint = RegionCandidate(
        region_id="r_chart",
        page=1,
        bbox_norm=(0.1, 0.3, 0.9, 0.5),
        region_type="picture",
        score=0.9,
        supporting_signals=["figure_class=line_chart"],
        expansion_hints=["caption"],  # rerank said: this chart needs a caption
    )
    regions = RegionsEvent(
        candidates=[
            primary_with_hint,
            # Lower-scoring caption would lose without the hint boost.
            _region(
                page=1,
                bbox_norm=(0.1, 0.55, 0.9, 0.58),
                region_type="caption",
                score=0.5,
            ),
            # Higher-scoring section_header takes the title-rule slot.
            _region(
                page=1,
                bbox_norm=(0.1, 0.20, 0.9, 0.25),
                region_type="section_header",
                score=0.85,
            ),
        ]
    )
    out = await expand_context(
        EvidenceEvent(packets=[figure]),
        regions=regions,
        pdf_path=tmp_path / "doc.pdf",
    )
    types = out.packets[0].linked_neighbor_types
    # Both a caption and a title attach (one per rule).
    assert "caption" in types
    assert "title" in types  # graph role for section_header is "title"
