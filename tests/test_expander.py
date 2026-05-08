"""Tests for `focusparse.pipeline.expander.expand_context` (sub-phase 2h).

Covers the neighbor-attachment logic:
  * passthrough when no region list or no crop source is available
  * finds caption/footnote/section_header/title neighbors that overlap the
    padded packet bbox
  * ignores unrelated region types (text/picture) unless reranker tags context
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
from focusparse.pipeline.expander import _neighbor_types_from_verifier_reason, expand_context


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


def _write_page_png(path: Path, *, size=(200, 100)) -> None:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", size, "white")
    ImageDraw.Draw(img).text((10, 10), "caption text", fill="black")
    img.save(path)


# ---------------------------------------------------------------------------
# Passthrough paths
# ---------------------------------------------------------------------------


async def test_passthrough_when_no_regions():
    """Without a regions list, the expander can't find neighbors — no-op."""
    ev = EvidenceEvent(packets=[_packet(packet_id="p0", page=1, bbox_norm=(0, 0, 0.5, 0.5))])
    out = await expand_context(ev, regions=None, pdf_path=Path("/fake.pdf"))
    assert out.packets == ev.packets


async def test_passthrough_when_no_pdf_path():
    """Without a PDF or page image fallback, return evidence unchanged."""
    ev = EvidenceEvent(packets=[_packet(packet_id="p0", page=1, bbox_norm=(0, 0, 0.5, 0.5))])
    regions = RegionsEvent(
        candidates=[
            _region(page=1, bbox_norm=(0, 0.5, 0.5, 0.6), region_type="caption"),
        ]
    )
    out = await expand_context(ev, regions=regions, pdf_path=None)
    assert out.packets == ev.packets


async def test_no_pdf_uses_page_image_for_neighbor_crop_and_text(tmp_path, monkeypatch):
    """When PDFs are absent, linked neighbor crops can come from staged page PNGs."""
    monkeypatch.setattr(
        "focusparse.pipeline.expander._ocr_existing_crop",
        lambda crop_path: ("caption from page image", 0.8),
    )
    page_image = tmp_path / "p1.png"
    _write_page_png(page_image)
    ev = EvidenceEvent(packets=[_packet(packet_id="p0", page=1, bbox_norm=(0.1, 0.1, 0.9, 0.4))])
    regions = RegionsEvent(
        candidates=[
            _region(page=1, bbox_norm=(0.1, 0.1, 0.9, 0.4), region_type="picture"),
            _region(page=1, bbox_norm=(0.15, 0.42, 0.85, 0.48), region_type="caption"),
        ]
    )
    out = await expand_context(
        ev,
        regions=regions,
        pdf_path=None,
        images_by_page={1: page_image},
        crop_cache_dir=tmp_path / "crops",
    )
    packet = out.packets[0]
    assert len(packet.linked_crop_refs) == 1
    assert Path(packet.linked_crop_refs[0]).exists()
    assert packet.linked_neighbor_types == ["caption"]
    assert packet.text_layer_snippet == "Context [caption]: caption from page image"


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
    # inspect_region always crops the linked neighbor image; text/OCR context
    # extraction may add more calls.
    image_calls = [c for c in calls if c["mode"] == "image"]
    assert len(image_calls) == 1
    assert image_calls[0]["expansion"] == "none"


async def test_attached_neighbor_text_reaches_packet_snippet(tmp_path, monkeypatch):
    calls: list = []
    _install_fake_inspect(monkeypatch, calls=calls)
    text_cache = tmp_path / "text_layer"
    seen: dict = {}

    class _TextOut:
        text = "Figure 3. Output ripple at 500 mA"
        source = "native"

    async def _fake_get_text_layer(inp, *, cache_dir=None):
        seen["page"] = inp.page
        seen["bbox_norm"] = inp.bbox_norm
        seen["cache_dir"] = cache_dir
        return _TextOut()

    monkeypatch.setattr("focusparse.pipeline.expander.get_text_layer", _fake_get_text_layer)

    figure = _packet(
        packet_id="p0",
        page=1,
        bbox_norm=(0.1, 0.1, 0.9, 0.4),
        region_type="picture",
    )
    regions = RegionsEvent(
        candidates=[
            _region(page=1, bbox_norm=(0.1, 0.1, 0.9, 0.4), region_type="picture"),
            caption := _region(
                page=1,
                bbox_norm=(0.15, 0.42, 0.85, 0.48),
                region_type="caption",
            ),
        ]
    )

    out = await expand_context(
        EvidenceEvent(packets=[figure]),
        regions=regions,
        pdf_path=tmp_path / "doc.pdf",
        text_layer_cache_dir=text_cache,
    )

    packet = out.packets[0]
    assert packet.linked_neighbor_types == ["caption"]
    assert packet.text_layer_snippet == "Context [caption]: Figure 3. Output ripple at 500 mA"
    assert seen == {
        "page": 1,
        "bbox_norm": list(caption.bbox_norm),
        "cache_dir": text_cache,
    }


async def test_retry_expand_does_not_duplicate_existing_neighbor_context(tmp_path, monkeypatch):
    """Verifier retries can call expand_context on an already-expanded packet.
    Reattaching the same caption should be a no-op, not another context line."""
    calls: list = []
    _install_fake_inspect(monkeypatch, calls=calls)

    class _TextOut:
        text = "Figure 31. Large-Signal Step Response"
        source = "native"

    async def _fake_get_text_layer(inp, *, cache_dir=None):
        return _TextOut()

    monkeypatch.setattr("focusparse.pipeline.expander.get_text_layer", _fake_get_text_layer)

    figure = _packet(
        packet_id="p0",
        page=1,
        bbox_norm=(0.1, 0.1, 0.9, 0.4),
        region_type="picture",
    )
    regions = RegionsEvent(
        candidates=[
            _region(page=1, bbox_norm=(0.1, 0.1, 0.9, 0.4), region_type="picture"),
            _region(page=1, bbox_norm=(0.15, 0.42, 0.85, 0.48), region_type="caption"),
        ]
    )

    first = await expand_context(
        EvidenceEvent(packets=[figure]),
        regions=regions,
        pdf_path=tmp_path / "doc.pdf",
    )
    second = await expand_context(
        first,
        regions=regions,
        pdf_path=tmp_path / "doc.pdf",
    )

    packet = second.packets[0]
    assert packet == first.packets[0]
    assert packet.text_layer_snippet.count("Context [caption]:") == 1
    assert packet.provenance.args_hash.count("expand_context:n1") == 1


async def test_expand_context_deduplicates_repeated_context_text(tmp_path, monkeypatch):
    """Broad neighbor scans can find duplicate captions. Keep the crops, but
    only show the reasoner/verifier one copy of the repeated text line."""
    calls: list = []
    _install_fake_inspect(monkeypatch, calls=calls)

    class _TextOut:
        text = "Figure 31. Large-Signal Step Response"
        source = "native"

    async def _fake_get_text_layer(inp, *, cache_dir=None):
        return _TextOut()

    monkeypatch.setattr("focusparse.pipeline.expander.get_text_layer", _fake_get_text_layer)

    figure = _packet(
        packet_id="p0",
        page=1,
        bbox_norm=(0.1, 0.1, 0.9, 0.4),
        region_type="picture",
    )
    regions = RegionsEvent(
        candidates=[
            _region(page=1, bbox_norm=(0.1, 0.1, 0.9, 0.4), region_type="picture"),
            _region_with_signals(
                page=1,
                bbox_norm=(0.15, 0.42, 0.85, 0.48),
                region_type="caption",
                relevance=0.9,
            ),
            _region_with_signals(
                page=1,
                bbox_norm=(0.15, 0.45, 0.85, 0.49),
                region_type="caption",
                relevance=0.8,
            ),
        ]
    )

    out = await expand_context(
        EvidenceEvent(packets=[figure]),
        regions=regions,
        pdf_path=tmp_path / "doc.pdf",
        max_neighbors_per_packet=2,
    )

    packet = out.packets[0]
    assert len(packet.linked_crop_refs) == 2
    assert packet.text_layer_snippet.count("Figure 31. Large-Signal Step Response") == 1


async def test_mismatched_figure_caption_is_not_attached(tmp_path, monkeypatch):
    """If the packet OCR says Figure 31, a neighboring Figure 33 caption is
    misleading context and should be dropped after text extraction."""
    calls: list = []
    _install_fake_inspect(monkeypatch, calls=calls)

    class _TextOut:
        source = "native"

        def __init__(self, text: str):
            self.text = text

    async def _fake_get_text_layer(inp, *, cache_dir=None):
        if inp.bbox_norm[1] < 0.5:
            return _TextOut("Figure 31. Large-Signal Step Response")
        return _TextOut("Figure 33. Large-Signal Step Response")

    monkeypatch.setattr("focusparse.pipeline.expander.get_text_layer", _fake_get_text_layer)

    figure = _packet(
        packet_id="p0",
        page=1,
        bbox_norm=(0.1, 0.1, 0.9, 0.4),
        region_type="picture",
    ).model_copy(update={"ocr_snippet": "OCR: Figure 31. VOUT (400mV/div)"})
    regions = RegionsEvent(
        candidates=[
            _region(page=1, bbox_norm=(0.1, 0.1, 0.9, 0.4), region_type="picture"),
            _region(page=1, bbox_norm=(0.15, 0.42, 0.85, 0.48), region_type="caption"),
            _region(page=1, bbox_norm=(0.15, 0.52, 0.85, 0.58), region_type="caption"),
        ]
    )

    out = await expand_context(
        EvidenceEvent(packets=[figure]),
        regions=regions,
        pdf_path=tmp_path / "doc.pdf",
        max_neighbors_per_packet=2,
    )

    packet = out.packets[0]
    assert packet.linked_neighbor_types == ["caption"]
    assert len(packet.linked_crop_refs) == 1
    assert "0.42" in packet.linked_crop_refs[0]
    assert "Figure 31. Large-Signal Step Response" in packet.ocr_snippet
    assert "Figure 33" not in packet.ocr_snippet


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
        use_evidence_graph=True,  # graph walker exercised explicitly
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
        use_evidence_graph=True,  # opt into the graph walker (default off)
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
        # Pre-Phase-B1.5 default behavior — kept as a regression test for the
        # provenance tagging shape; the fallback budget tightening is
        # exercised separately in test_query_aware_planner_no_hint_*.
        max_neighbors_per_packet=4,
    )
    args_hash = out.packets[0].provenance.args_hash
    # Prior inspector tag is preserved + our stamp appended. Without a
    # planner hint or rerank signal, the legacy spatial fallback runs and
    # caps at _FALLBACK_MAX_NEIGHBORS_PER_PACKET (1 as of Phase B1.5).
    assert "seed" in args_hash
    assert "expand_context:n1" in args_hash


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
    # Tell the planner we want both kinds of neighbors so the new query-aware
    # gate doesn't drop one. This is a "crop failure resilience" test, not
    # a query-conditioning test.
    regions = RegionsEvent(
        candidates=[
            _region(page=1, bbox_norm=failing_bbox, region_type="caption"),
            _region(page=1, bbox_norm=(0.1, 0.56, 0.9, 0.58), region_type="footnote"),
        ]
    )
    plan = PlanEvent(
        question_family="single_value_lookup",
        evidence_types=["caption", "footnote"],
        budget_class="easy_local",
        routing_policy="layout_first",
        max_tool_calls=8,
        max_crops=8,
        max_vlm_calls=4,
    )
    out = await expand_context(
        EvidenceEvent(packets=[figure]),
        regions=regions,
        pdf_path=tmp_path / "doc.pdf",
        plan=plan,
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
        use_evidence_graph=True,  # opt into graph walker (default off)
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
        use_evidence_graph=True,  # graph still falls through for unknown primary
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
        use_evidence_graph=True,  # opt into graph walker (default off)
    )
    types = out.packets[0].linked_neighbor_types
    # Both a caption and a title attach (one per rule).
    assert "caption" in types
    assert "title" in types  # graph role for section_header is "title"


# ---------------------------------------------------------------------------
# 2026-05-05 sprint: query-aware neighbor selection (Phase 6 #3).
#
# The rebaseline-v2 finding: query-blind expand_context attached ~13
# neighbors per example and hurt 11 of the 13 affected examples on +4 vs +2.
# These tests pin the new selection signal precedence:
#   1. Reranker `relevance` — drop below threshold; rank by score.
#   2. Reranker `needed_for` ∈ context roles — attach.
#   3. Planner `evidence_types` — attach matching region_types only.
#   4. Spatial-only fallback — bounded to fewer neighbors.
# ---------------------------------------------------------------------------


from focusparse.pipeline.events import PlanEvent  # noqa: E402


def _region_with_signals(
    *,
    page: int,
    bbox_norm: tuple[float, float, float, float],
    region_type: str,
    score: float = 0.9,
    relevance: float | None = None,
    needed_for: str | None = None,
) -> RegionCandidate:
    return RegionCandidate(
        region_id=f"r_{page}_{region_type}_{relevance}_{needed_for}",
        page=page,
        bbox_norm=bbox_norm,
        region_type=region_type,
        score=score,
        relevance=relevance,
        needed_for=needed_for,
    )


def _plan(
    *,
    evidence_types: list[str] | None = None,
    question_family: str = "spec_table_cell_retrieval",
) -> PlanEvent:
    return PlanEvent(
        question_family=question_family,
        evidence_types=evidence_types or [],
        budget_class="easy_local",
        routing_policy="layout_first",
        max_tool_calls=12,
        max_crops=8,
        max_vlm_calls=4,
    )


async def test_query_aware_filters_to_planner_evidence_types(tmp_path, monkeypatch):
    """When plan asks for 'caption', only captions attach — not footnotes."""
    calls: list = []
    _install_fake_inspect(monkeypatch, calls=calls)
    ev = EvidenceEvent(
        packets=[_packet(packet_id="p0", page=1, bbox_norm=(0.10, 0.20, 0.50, 0.60))]
    )
    regions = RegionsEvent(
        candidates=[
            _region(
                page=1,
                bbox_norm=(0.10, 0.62, 0.50, 0.66),  # caption just below
                region_type="caption",
            ),
            _region(
                page=1,
                bbox_norm=(0.10, 0.18, 0.50, 0.21),  # footnote just above
                region_type="footnote",
            ),
        ]
    )
    out = await expand_context(
        ev,
        regions=regions,
        pdf_path=Path("/fake.pdf"),
        plan=_plan(evidence_types=["caption"]),
    )
    types = out.packets[0].linked_neighbor_types
    assert "caption" in types
    assert "footnote" not in types  # planner didn't ask for footnotes


async def test_planner_hint_initial_expand_uses_conservative_cap(tmp_path, monkeypatch):
    """Coarse planner hints should not attach every nearby context block before verification."""
    calls: list = []
    _install_fake_inspect(monkeypatch, calls=calls)
    ev = EvidenceEvent(
        packets=[_packet(packet_id="p0", page=1, bbox_norm=(0.30, 0.40, 0.70, 0.50))]
    )
    regions = RegionsEvent(
        candidates=[
            _region(page=1, bbox_norm=(0.30, 0.52, 0.70, 0.56), region_type="caption"),
            _region(page=1, bbox_norm=(0.30, 0.34, 0.70, 0.38), region_type="footnote"),
        ]
    )
    out = await expand_context(
        ev,
        regions=regions,
        pdf_path=Path("/fake.pdf"),
        plan=_plan(evidence_types=["caption", "footnote"]),
        max_neighbors_per_packet=2,
    )
    assert len(out.packets[0].linked_neighbor_types) == 1


async def test_retry_expand_looks_past_already_linked_neighbors(tmp_path, monkeypatch):
    """A verifier-triggered wider pass should not stop at duplicate neighbors."""
    calls: list = []
    _install_fake_inspect(monkeypatch, calls=calls)
    ev = EvidenceEvent(
        packets=[_packet(packet_id="p0", page=1, bbox_norm=(0.30, 0.40, 0.70, 0.50))]
    )
    regions = RegionsEvent(
        candidates=[
            _region_with_signals(
                page=1,
                bbox_norm=(0.30, 0.52, 0.70, 0.56),
                region_type="caption",
                relevance=0.9,
            ),
            _region_with_signals(
                page=1,
                bbox_norm=(0.30, 0.34, 0.70, 0.38),
                region_type="footnote",
                relevance=0.8,
            ),
            _region_with_signals(
                page=1,
                bbox_norm=(0.30, 0.57, 0.70, 0.60),
                region_type="title",
                relevance=0.7,
            ),
        ]
    )
    first = await expand_context(
        ev,
        regions=regions,
        pdf_path=Path("/fake.pdf"),
        max_neighbors_per_packet=2,
    )
    assert first.packets[0].linked_neighbor_types == ["caption", "footnote"]

    second = await expand_context(
        first,
        regions=regions,
        pdf_path=Path("/fake.pdf"),
        max_neighbors_per_packet=2,
        adjacency_pad=0.10,
    )
    assert second.packets[0].linked_neighbor_types == ["caption", "footnote", "title"]


async def test_verifier_directed_chart_retry_allows_legend_and_axis_labels(tmp_path, monkeypatch):
    calls: list = []
    _install_fake_inspect(monkeypatch, calls=calls)
    ev = EvidenceEvent(
        packets=[_packet(packet_id="p0", page=1, bbox_norm=(0.30, 0.40, 0.70, 0.50))]
    )
    regions = RegionsEvent(
        candidates=[
            _region(page=1, bbox_norm=(0.30, 0.52, 0.70, 0.56), region_type="legend"),
            _region(page=1, bbox_norm=(0.30, 0.34, 0.70, 0.38), region_type="axis_label"),
            _region(page=1, bbox_norm=(0.30, 0.58, 0.70, 0.62), region_type="footnote"),
        ]
    )
    out = await expand_context(
        ev,
        regions=regions,
        pdf_path=Path("/fake.pdf"),
        plan=_plan(evidence_types=["chart"]),
        verifier_reason="missing legend and axis labels",
        max_neighbors_per_packet=2,
    )
    assert set(out.packets[0].linked_neighbor_types) == {"axis_label", "legend"}


async def test_verifier_reason_can_expand_beyond_original_plan_hint(tmp_path, monkeypatch):
    """Verifier feedback should steer retries toward the missing context type."""
    calls: list = []
    _install_fake_inspect(monkeypatch, calls=calls)
    ev = EvidenceEvent(
        packets=[_packet(packet_id="p0", page=1, bbox_norm=(0.30, 0.40, 0.70, 0.50))]
    )
    regions = RegionsEvent(
        candidates=[
            _region(page=1, bbox_norm=(0.30, 0.52, 0.70, 0.56), region_type="caption"),
            _region(page=1, bbox_norm=(0.30, 0.34, 0.70, 0.38), region_type="footnote"),
        ]
    )
    out = await expand_context(
        ev,
        regions=regions,
        pdf_path=Path("/fake.pdf"),
        plan=_plan(evidence_types=["caption"]),
        verifier_reason="unsupported: cited table row is missing the footnote note",
        max_neighbors_per_packet=2,
    )
    assert set(out.packets[0].linked_neighbor_types) == {"caption", "footnote"}


def test_verifier_reason_allows_table_cell_context_types():
    allowed = _neighbor_types_from_verifier_reason("missing row and column cell value")
    assert {"table", "text", "list-item", "key-value region"} <= allowed


async def test_verifier_directed_table_retry_allows_nearby_text_regions(tmp_path, monkeypatch):
    calls: list = []
    _install_fake_inspect(monkeypatch, calls=calls)
    ev = EvidenceEvent(
        packets=[_packet(packet_id="p0", page=1, bbox_norm=(0.30, 0.40, 0.70, 0.50))]
    )
    regions = RegionsEvent(
        candidates=[
            _region(page=1, bbox_norm=(0.30, 0.52, 0.70, 0.56), region_type="text"),
            _region(page=1, bbox_norm=(0.30, 0.34, 0.70, 0.38), region_type="table"),
            _region(page=1, bbox_norm=(0.30, 0.58, 0.70, 0.62), region_type="picture"),
        ]
    )

    initial = await expand_context(
        ev,
        regions=regions,
        pdf_path=Path("/fake.pdf"),
        plan=_plan(evidence_types=["caption"]),
        max_neighbors_per_packet=2,
    )
    assert initial.packets[0].linked_neighbor_types == []

    retry = await expand_context(
        ev,
        regions=regions,
        pdf_path=Path("/fake.pdf"),
        plan=_plan(evidence_types=["caption"]),
        verifier_reason="missing row/column cell value from the table",
        max_neighbors_per_packet=2,
    )
    assert set(retry.packets[0].linked_neighbor_types) == {"table", "text"}


async def test_target_packet_ids_limit_which_packets_expand(tmp_path, monkeypatch):
    calls: list = []
    _install_fake_inspect(monkeypatch, calls=calls)
    ev = EvidenceEvent(
        packets=[
            _packet(packet_id="p0", page=1, bbox_norm=(0.10, 0.20, 0.40, 0.40)),
            _packet(packet_id="p1", page=1, bbox_norm=(0.60, 0.20, 0.90, 0.40)),
        ]
    )
    regions = RegionsEvent(
        candidates=[
            _region(page=1, bbox_norm=(0.10, 0.42, 0.40, 0.46), region_type="caption"),
            _region(page=1, bbox_norm=(0.60, 0.42, 0.90, 0.46), region_type="caption"),
        ]
    )
    out = await expand_context(
        ev,
        regions=regions,
        pdf_path=Path("/fake.pdf"),
        plan=_plan(evidence_types=["caption"]),
        target_packet_ids=["p1"],
    )
    assert out.packets[0].linked_neighbor_types == []
    assert out.packets[1].linked_neighbor_types == ["caption"]


async def test_empty_target_packet_ids_expand_no_packets(tmp_path, monkeypatch):
    """An explicit empty target list means a retry has no safe packet anchor."""
    calls: list = []
    _install_fake_inspect(monkeypatch, calls=calls)
    ev = EvidenceEvent(
        packets=[
            _packet(packet_id="p0", page=1, bbox_norm=(0.10, 0.20, 0.40, 0.40)),
            _packet(packet_id="p1", page=1, bbox_norm=(0.60, 0.20, 0.90, 0.40)),
        ]
    )
    regions = RegionsEvent(
        candidates=[
            _region(page=1, bbox_norm=(0.10, 0.42, 0.40, 0.46), region_type="caption"),
            _region(page=1, bbox_norm=(0.60, 0.42, 0.90, 0.46), region_type="caption"),
        ]
    )
    out = await expand_context(
        ev,
        regions=regions,
        pdf_path=Path("/fake.pdf"),
        plan=_plan(evidence_types=["caption"]),
        target_packet_ids=[],
    )
    assert [p.linked_neighbor_types for p in out.packets] == [[], []]
    assert calls == []


async def test_query_aware_planner_no_hint_uses_fallback_max_1(tmp_path, monkeypatch):
    """Without planner hint AND without rerank scores, the spatial-only
    fallback is bounded to _FALLBACK_MAX_NEIGHBORS_PER_PACKET (= 1 as of
    Phase B1.5, tightened from 2 after the B1 A/B showed too many marginal-
    relevance neighbors per packet)."""
    calls: list = []
    _install_fake_inspect(monkeypatch, calls=calls)
    ev = EvidenceEvent(
        packets=[_packet(packet_id="p0", page=1, bbox_norm=(0.30, 0.40, 0.70, 0.50))]
    )
    # 4 spatially-adjacent annotations; without any query signal, only the
    # closest one survives the fallback budget.
    regions = RegionsEvent(
        candidates=[
            _region(page=1, bbox_norm=(0.30, 0.52, 0.70, 0.56), region_type="caption"),
            _region(page=1, bbox_norm=(0.30, 0.34, 0.70, 0.38), region_type="footnote"),
            _region(page=1, bbox_norm=(0.30, 0.30, 0.70, 0.33), region_type="section_header"),
            _region(page=1, bbox_norm=(0.30, 0.58, 0.70, 0.62), region_type="title"),
        ]
    )
    out = await expand_context(
        ev,
        regions=regions,
        pdf_path=Path("/fake.pdf"),
        plan=None,
    )
    n_attached = len(out.packets[0].linked_crop_refs)
    assert n_attached == 1  # _FALLBACK_MAX_NEIGHBORS_PER_PACKET


async def test_query_aware_rerank_relevance_filters_low_scoring(tmp_path, monkeypatch):
    """Reranker scored a candidate at 0.1 → drop it even if spatially adjacent."""
    calls: list = []
    _install_fake_inspect(monkeypatch, calls=calls)
    ev = EvidenceEvent(
        packets=[_packet(packet_id="p0", page=1, bbox_norm=(0.10, 0.20, 0.50, 0.60))]
    )
    regions = RegionsEvent(
        candidates=[
            _region_with_signals(
                page=1,
                bbox_norm=(0.10, 0.62, 0.50, 0.66),
                region_type="caption",
                relevance=0.1,  # below default 0.3 threshold
            ),
            _region_with_signals(
                page=1,
                bbox_norm=(0.10, 0.16, 0.50, 0.19),
                region_type="footnote",
                relevance=0.8,  # above threshold
            ),
        ]
    )
    out = await expand_context(
        ev,
        regions=regions,
        pdf_path=Path("/fake.pdf"),
    )
    types = out.packets[0].linked_neighbor_types
    assert "footnote" in types
    assert "caption" not in types  # below relevance threshold


async def test_query_aware_rerank_needed_for_role_attaches(tmp_path, monkeypatch):
    """Reranker tagged a region with `needed_for=caption_context` → attach
    even without an explicit relevance score."""
    calls: list = []
    _install_fake_inspect(monkeypatch, calls=calls)
    ev = EvidenceEvent(
        packets=[_packet(packet_id="p0", page=1, bbox_norm=(0.10, 0.20, 0.50, 0.60))]
    )
    regions = RegionsEvent(
        candidates=[
            _region_with_signals(
                page=1,
                bbox_norm=(0.10, 0.62, 0.50, 0.66),
                region_type="caption",
                needed_for="caption_context",
            ),
        ]
    )
    out = await expand_context(
        ev,
        regions=regions,
        pdf_path=Path("/fake.pdf"),
    )
    assert "caption" in out.packets[0].linked_neighbor_types


async def test_query_aware_needed_for_role_can_attach_plain_text(tmp_path, monkeypatch):
    """A reranker-tagged legend/axis context block may arrive from layout as
    plain `text`; explicit `needed_for` context roles should still attach it."""
    calls: list = []
    _install_fake_inspect(monkeypatch, calls=calls)
    ev = EvidenceEvent(
        packets=[_packet(packet_id="p0", page=1, bbox_norm=(0.10, 0.20, 0.50, 0.60))]
    )
    regions = RegionsEvent(
        candidates=[
            _region_with_signals(
                page=1,
                bbox_norm=(0.10, 0.62, 0.50, 0.66),
                region_type="text",
                needed_for="legend_binding",
            ),
        ]
    )
    out = await expand_context(
        ev,
        regions=regions,
        pdf_path=Path("/fake.pdf"),
    )
    packet = out.packets[0]
    assert len(packet.linked_crop_refs) == 1
    assert packet.linked_neighbor_types == ["legend_binding"]


async def test_query_aware_planner_hint_drops_unmatched_types(tmp_path, monkeypatch):
    """When plan asks for 'caption' only, a `section_header` candidate is
    dropped — even if it's spatially adjacent and the reranker didn't score it."""
    calls: list = []
    _install_fake_inspect(monkeypatch, calls=calls)
    ev = EvidenceEvent(
        packets=[_packet(packet_id="p0", page=1, bbox_norm=(0.10, 0.20, 0.50, 0.60))]
    )
    regions = RegionsEvent(
        candidates=[
            _region(page=1, bbox_norm=(0.10, 0.16, 0.50, 0.19), region_type="section_header"),
            _region(page=1, bbox_norm=(0.10, 0.62, 0.50, 0.66), region_type="caption"),
        ]
    )
    out = await expand_context(
        ev,
        regions=regions,
        pdf_path=Path("/fake.pdf"),
        plan=_plan(evidence_types=["caption"]),
    )
    types = out.packets[0].linked_neighbor_types
    assert "caption" in types
    assert "section_header" not in types
    assert "section-header" not in types


async def test_query_aware_rerank_signal_unlocks_default_budget(tmp_path, monkeypatch):
    """When reranker scored ANY candidate above threshold, the default cap
    of `_DEFAULT_MAX_NEIGHBORS_PER_PACKET` (= 2 as of Phase B1.5) applies
    instead of the tighter no-signal fallback."""
    calls: list = []
    _install_fake_inspect(monkeypatch, calls=calls)
    ev = EvidenceEvent(
        packets=[_packet(packet_id="p0", page=1, bbox_norm=(0.30, 0.40, 0.70, 0.50))]
    )
    # 4 candidates, all relevance=0.7 (above threshold 0.5), all inside the
    # packet's 8% padded bbox (packet y=0.40-0.50, padded to 0.32-0.58).
    regions = RegionsEvent(
        candidates=[
            _region_with_signals(
                page=1,
                bbox_norm=(0.30, 0.52, 0.70, 0.56),
                region_type="caption",
                relevance=0.7,
            ),
            _region_with_signals(
                page=1,
                bbox_norm=(0.30, 0.34, 0.70, 0.38),
                region_type="footnote",
                relevance=0.7,
            ),
            _region_with_signals(
                page=1,
                bbox_norm=(0.30, 0.33, 0.70, 0.36),
                region_type="section_header",
                relevance=0.7,
            ),
            _region_with_signals(
                page=1,
                bbox_norm=(0.30, 0.55, 0.70, 0.57),
                region_type="title",
                relevance=0.7,
            ),
        ]
    )
    out = await expand_context(
        ev,
        regions=regions,
        pdf_path=Path("/fake.pdf"),
        plan=None,
    )
    # 2 = _DEFAULT_MAX_NEIGHBORS_PER_PACKET (Phase B1.5).
    assert len(out.packets[0].linked_crop_refs) == 2


async def test_query_aware_relevance_orders_neighbors_by_score(tmp_path, monkeypatch):
    """Higher-relevance neighbors come first when capping to max_n=2."""
    calls: list = []
    _install_fake_inspect(monkeypatch, calls=calls)
    ev = EvidenceEvent(
        packets=[_packet(packet_id="p0", page=1, bbox_norm=(0.30, 0.40, 0.70, 0.50))]
    )
    regions = RegionsEvent(
        candidates=[
            _region_with_signals(
                page=1,
                bbox_norm=(0.30, 0.52, 0.70, 0.56),
                region_type="caption",
                relevance=0.4,  # mid
            ),
            _region_with_signals(
                page=1,
                bbox_norm=(0.30, 0.34, 0.70, 0.38),
                region_type="footnote",
                relevance=0.9,  # highest
            ),
            _region_with_signals(
                page=1,
                bbox_norm=(0.30, 0.30, 0.70, 0.33),
                region_type="title",
                relevance=0.7,
            ),
        ]
    )
    out = await expand_context(
        ev,
        regions=regions,
        pdf_path=Path("/fake.pdf"),
        max_neighbors_per_packet=2,  # explicit cap to test ordering
    )
    types = out.packets[0].linked_neighbor_types
    # The 0.9 footnote and 0.7 title win over the 0.4 caption.
    assert types[0] == "footnote"
    assert types[1] == "title"
    assert "caption" not in types
