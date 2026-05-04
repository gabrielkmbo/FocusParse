"""Tests for `focusparse.pipeline.inspector.inspect_regions` (sub-phase 2g).

Covers the smart-deterministic tool dispatcher:
  * budget: plan.max_crops caps how many regions get inspected
  * ranking: higher-score regions go first
  * visual regions (picture/chart) get crop only, no OCR
  * text regions with a PDF use get_text_layer
  * OCR fallback when native text is empty (image-only PDFs)
  * OCR fallback when no PDF is supplied at all
  * packet fields populate: local_crop_ref / text_layer_snippet / ocr_snippet
  * provenance.tool reflects which path ran (deterministic vs fallback)
  * confidence folds OCR confidence into region score
  * unknown region_type behaves like text-bearing (doesn't silently skip OCR)

Monkeypatches the two tools so no PyMuPDF, Tesseract, or HF calls happen.
"""

from __future__ import annotations

import pytest

from focusparse.pipeline.events import (
    PlanEvent,
    QuestionEvent,
    RegionCandidate,
    RegionsEvent,
)
from focusparse.pipeline.inspector import inspect_regions


def _q() -> QuestionEvent:
    return QuestionEvent(
        example_id="ex-1",
        question="What is VCC max?",
        doc_id="datasheet-A",
        pages_available=10,
    )


def _plan(max_crops: int = 8) -> PlanEvent:
    return PlanEvent(
        question_family="single_value_lookup",
        evidence_types=["table"],
        budget_class="easy_local",
        routing_policy="layout_first",
        max_tool_calls=12,
        max_crops=max_crops,
        max_vlm_calls=4,
    )


def _region(
    *,
    region_id: str,
    page: int,
    bbox_norm: tuple[float, float, float, float],
    region_type: str | None = None,
    score: float = 0.8,
    supporting_signals: list[str] | None = None,
) -> RegionCandidate:
    return RegionCandidate(
        region_id=region_id,
        page=page,
        bbox_norm=bbox_norm,
        region_type=region_type,
        score=score,
        supporting_signals=supporting_signals or [],
    )


class _FakeInspectOutput:
    def __init__(self, crop_ref: str, ocr_text: str | None, confidence: float = 1.0):
        self.crop_ref = crop_ref
        self.ocr_text = ocr_text
        self.confidence = confidence


class _FakeTextLayerOutput:
    def __init__(self, text: str, source: str = "native"):
        self.text = text
        self.source = source


def _install_fake_tools(
    monkeypatch,
    *,
    inspect_calls: list,
    text_calls: list,
    inspect_image_out: _FakeInspectOutput | None = None,
    inspect_element_out: _FakeInspectOutput | None = None,
    text_layer_out: _FakeTextLayerOutput | None = None,
):
    """Install per-tool monkeypatches and append captured kwargs."""

    async def _fake_inspect(inp, *, cache_dir=None):
        inspect_calls.append(
            {
                "doc_path": inp.doc_path,
                "page": inp.page,
                "bbox_norm": inp.bbox_norm,
                "mode": inp.mode,
                "cache_dir": cache_dir,
            }
        )
        if inp.mode == "image":
            return inspect_image_out or _FakeInspectOutput(
                crop_ref=f"/crops/p{inp.page}_{inp.mode}.png", ocr_text=None
            )
        return inspect_element_out or _FakeInspectOutput(
            crop_ref=f"/crops/p{inp.page}_{inp.mode}.png",
            ocr_text="OCR TEXT",
            confidence=0.85,
        )

    async def _fake_text_layer(inp, *, cache_dir=None):
        text_calls.append(
            {
                "doc_path": inp.doc_path,
                "page": inp.page,
                "bbox_norm": inp.bbox_norm,
                "cache_dir": cache_dir,
            }
        )
        return text_layer_out or _FakeTextLayerOutput(text="NATIVE TEXT")

    monkeypatch.setattr("focusparse.pipeline.inspector.inspect_region", _fake_inspect)
    monkeypatch.setattr("focusparse.pipeline.inspector.get_text_layer", _fake_text_layer)


# ---------------------------------------------------------------------------
# Budget + ranking
# ---------------------------------------------------------------------------


async def test_inspect_regions_caps_at_max_crops(tmp_path, monkeypatch):
    inspect_calls: list = []
    text_calls: list = []
    _install_fake_tools(monkeypatch, inspect_calls=inspect_calls, text_calls=text_calls)

    regions = RegionsEvent(
        candidates=[
            _region(region_id=f"r{i}", page=1, bbox_norm=(0, 0, 0.5, 0.5), score=0.9 - i * 0.05)
            for i in range(10)
        ]
    )
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    ev = await inspect_regions(
        _q(),
        _plan(max_crops=3),
        regions,
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
    )
    assert len(ev.packets) == 3


async def test_inspect_regions_ranks_by_score_desc(tmp_path, monkeypatch):
    """Highest-scoring region goes first (becomes pkt_000)."""
    inspect_calls: list = []
    text_calls: list = []
    _install_fake_tools(monkeypatch, inspect_calls=inspect_calls, text_calls=text_calls)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    regions = RegionsEvent(
        candidates=[
            _region(region_id="low", page=1, bbox_norm=(0, 0, 0.1, 0.1), score=0.2),
            _region(region_id="high", page=2, bbox_norm=(0, 0, 0.9, 0.9), score=0.95),
            _region(region_id="mid", page=3, bbox_norm=(0, 0, 0.5, 0.5), score=0.5),
        ]
    )
    ev = await inspect_regions(
        _q(),
        _plan(max_crops=3),
        regions,
        images_by_page={1: tmp_path / "p1.png", 2: tmp_path / "p2.png", 3: tmp_path / "p3.png"},
        pdf_path=pdf,
    )
    assert [p.page for p in ev.packets] == [2, 3, 1]
    assert ev.packets[0].packet_id == "pkt_000"


# ---------------------------------------------------------------------------
# Per-region-type routing
# ---------------------------------------------------------------------------


async def test_visual_region_skips_ocr(tmp_path, monkeypatch):
    inspect_calls: list = []
    text_calls: list = []
    _install_fake_tools(monkeypatch, inspect_calls=inspect_calls, text_calls=text_calls)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    regions = RegionsEvent(
        candidates=[
            _region(
                region_id="pic",
                page=1,
                bbox_norm=(0, 0, 0.5, 0.5),
                region_type="picture",
                score=0.9,
            )
        ]
    )
    ev = await inspect_regions(
        _q(),
        _plan(),
        regions,
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
    )
    # Only the image-mode crop call; no get_text_layer, no element-mode OCR.
    assert [c["mode"] for c in inspect_calls] == ["image"]
    assert text_calls == []
    packet = ev.packets[0]
    assert packet.ocr_snippet is None
    assert packet.text_layer_snippet is None
    assert packet.commit_level == "image"


async def test_text_region_uses_native_text_layer(tmp_path, monkeypatch):
    inspect_calls: list = []
    text_calls: list = []
    _install_fake_tools(
        monkeypatch,
        inspect_calls=inspect_calls,
        text_calls=text_calls,
        text_layer_out=_FakeTextLayerOutput(text="VCC MAXIMUM 3.6V", source="native"),
    )
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    regions = RegionsEvent(
        candidates=[
            _region(
                region_id="txt",
                page=2,
                bbox_norm=(0.1, 0.1, 0.5, 0.5),
                region_type="text",
                score=0.8,
            )
        ]
    )
    ev = await inspect_regions(
        _q(),
        _plan(),
        regions,
        images_by_page={2: tmp_path / "p2.png"},
        pdf_path=pdf,
    )
    # Image-mode crop + text_layer; no element-mode OCR (native text was good).
    modes = [c["mode"] for c in inspect_calls]
    assert modes == ["image"]
    assert len(text_calls) == 1
    packet = ev.packets[0]
    assert packet.text_layer_snippet == "VCC MAXIMUM 3.6V"
    assert packet.ocr_snippet is None
    assert packet.commit_level == "element"


async def test_text_region_falls_back_to_ocr_when_native_text_empty(tmp_path, monkeypatch):
    """Image-only PDF → get_text_layer returns empty → element-mode Tesseract kicks in."""
    inspect_calls: list = []
    text_calls: list = []
    _install_fake_tools(
        monkeypatch,
        inspect_calls=inspect_calls,
        text_calls=text_calls,
        text_layer_out=_FakeTextLayerOutput(text="", source="empty_native"),
        inspect_element_out=_FakeInspectOutput(
            crop_ref="/crops/p1_element.png", ocr_text="OCR FALLBACK TEXT", confidence=0.72
        ),
    )
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    regions = RegionsEvent(
        candidates=[
            _region(
                region_id="txt",
                page=1,
                bbox_norm=(0, 0, 0.5, 0.5),
                region_type="text",
                score=0.9,
            )
        ]
    )
    ev = await inspect_regions(
        _q(),
        _plan(),
        regions,
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
    )
    modes = [c["mode"] for c in inspect_calls]
    assert modes == ["image", "element"]
    packet = ev.packets[0]
    assert packet.text_layer_snippet is None
    assert packet.ocr_snippet == "OCR FALLBACK TEXT"
    # OCR confidence folds into packet confidence (min of score and OCR conf).
    assert packet.confidence == pytest.approx(0.72)


async def test_text_region_falls_back_to_ocr_when_whitespace_only(tmp_path, monkeypatch):
    """Whitespace-only native text (< _MIN_TEXT_LAYER_CHARS) should also trigger OCR fallback."""
    inspect_calls: list = []
    text_calls: list = []
    _install_fake_tools(
        monkeypatch,
        inspect_calls=inspect_calls,
        text_calls=text_calls,
        text_layer_out=_FakeTextLayerOutput(text=" .", source="native"),
        inspect_element_out=_FakeInspectOutput(
            crop_ref="/c.png", ocr_text="actual content", confidence=0.9
        ),
    )
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    regions = RegionsEvent(
        candidates=[
            _region(
                region_id="sparse",
                page=1,
                bbox_norm=(0, 0, 0.5, 0.5),
                region_type="text",
                score=0.9,
            )
        ]
    )
    ev = await inspect_regions(
        _q(),
        _plan(),
        regions,
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
    )
    assert ev.packets[0].ocr_snippet == "actual content"


async def test_unknown_region_type_still_gets_ocr(tmp_path, monkeypatch):
    inspect_calls: list = []
    text_calls: list = []
    _install_fake_tools(
        monkeypatch,
        inspect_calls=inspect_calls,
        text_calls=text_calls,
        text_layer_out=_FakeTextLayerOutput(text="", source="empty_native"),
    )
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    regions = RegionsEvent(
        candidates=[
            _region(region_id="?", page=1, bbox_norm=(0, 0, 0.5, 0.5), region_type=None, score=0.8)
        ]
    )
    await inspect_regions(
        _q(),
        _plan(),
        regions,
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
    )
    modes = [c["mode"] for c in inspect_calls]
    assert modes == ["image", "element"]  # OCR path ran


# ---------------------------------------------------------------------------
# No-PDF degraded path
# ---------------------------------------------------------------------------


async def test_no_pdf_path_produces_fallback_packets(tmp_path, monkeypatch):
    """Without a PDF, no tool calls are made; we still emit packets with the
    page image as a fallback ref so downstream stages don't see an empty set."""
    inspect_calls: list = []
    text_calls: list = []
    _install_fake_tools(monkeypatch, inspect_calls=inspect_calls, text_calls=text_calls)

    regions = RegionsEvent(
        candidates=[
            _region(
                region_id="r", page=1, bbox_norm=(0, 0, 0.5, 0.5), region_type="text", score=0.9
            )
        ]
    )
    ev = await inspect_regions(
        _q(),
        _plan(),
        regions,
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=None,
    )
    assert inspect_calls == []
    assert text_calls == []
    packet = ev.packets[0]
    assert packet.provenance.tool == "skeleton_inspector_fallback"
    # page_thumbnail + local_crop both point at the page image, matching the
    # pre-2g skeleton behavior.
    assert packet.local_crop_ref == str(tmp_path / "p1.png")


# ---------------------------------------------------------------------------
# Provenance + packet fields
# ---------------------------------------------------------------------------


async def test_provenance_encodes_tool_chain(tmp_path, monkeypatch):
    inspect_calls: list = []
    text_calls: list = []
    _install_fake_tools(
        monkeypatch,
        inspect_calls=inspect_calls,
        text_calls=text_calls,
        text_layer_out=_FakeTextLayerOutput(text="good text", source="native"),
    )
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    regions = RegionsEvent(
        candidates=[
            _region(
                region_id="r",
                page=1,
                bbox_norm=(0, 0, 0.5, 0.5),
                region_type="text",
                score=0.9,
            )
        ]
    )
    ev = await inspect_regions(
        _q(),
        _plan(),
        regions,
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
    )
    prov = ev.packets[0].provenance
    assert prov.tool == "deterministic_inspector"
    # args_hash encodes which tool sub-paths fired.
    assert "inspect_region:image" in prov.args_hash
    assert "get_text_layer:native" in prov.args_hash


async def test_cache_dirs_are_forwarded_to_tools(tmp_path, monkeypatch):
    inspect_calls: list = []
    text_calls: list = []
    _install_fake_tools(monkeypatch, inspect_calls=inspect_calls, text_calls=text_calls)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    crop_dir = tmp_path / "crops"
    text_dir = tmp_path / "text_layer"

    regions = RegionsEvent(
        candidates=[
            _region(
                region_id="r", page=1, bbox_norm=(0, 0, 0.5, 0.5), region_type="text", score=0.9
            )
        ]
    )
    await inspect_regions(
        _q(),
        _plan(),
        regions,
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
        crop_cache_dir=crop_dir,
        text_layer_cache_dir=text_dir,
    )
    assert inspect_calls[0]["cache_dir"] == crop_dir
    assert text_calls[0]["cache_dir"] == text_dir


# ---------------------------------------------------------------------------
# Resilience
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Evidence-type-aware ranking (smoke-test observation fix)
# ---------------------------------------------------------------------------


def _plan_with_evidence(evidence_types: list[str], max_crops: int = 3) -> PlanEvent:
    return PlanEvent(
        question_family="axis_value_interpolation",
        evidence_types=evidence_types,
        budget_class="easy_local",
        routing_policy="image_first",
        max_tool_calls=12,
        max_crops=max_crops,
        max_vlm_calls=4,
    )


async def test_figure_evidence_type_boosts_picture_over_text(tmp_path, monkeypatch):
    """RT-DETRv2 scores text > picture on the raw signal; when plan asks for
    figures, the inspector should still surface the picture first."""
    inspect_calls: list = []
    text_calls: list = []
    _install_fake_tools(monkeypatch, inspect_calls=inspect_calls, text_calls=text_calls)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    regions = RegionsEvent(
        candidates=[
            # Confident text — base-score winner under plain sort
            _region(
                region_id="t1",
                page=1,
                bbox_norm=(0, 0, 0.5, 0.5),
                region_type="text",
                score=0.92,
            ),
            # Confident section header — second under plain sort
            _region(
                region_id="h1",
                page=1,
                bbox_norm=(0, 0.5, 0.5, 0.6),
                region_type="section_header",
                score=0.88,
            ),
            # A moderate-score picture — should be boosted to #1
            _region(
                region_id="p1",
                page=1,
                bbox_norm=(0.5, 0, 1.0, 1.0),
                region_type="picture",
                score=0.7,
            ),
        ]
    )

    plan = _plan_with_evidence(["figure"], max_crops=3)
    ev = await inspect_regions(
        _q(),
        plan,
        regions,
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
    )
    # Picture (0.7 * 1.5 = 1.05) > text (0.92) > header (0.88).
    assert [p.region_type for p in ev.packets] == ["picture", "text", "section_header"]


async def test_table_evidence_type_boosts_table_regions(tmp_path, monkeypatch):
    inspect_calls: list = []
    text_calls: list = []
    _install_fake_tools(monkeypatch, inspect_calls=inspect_calls, text_calls=text_calls)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    regions = RegionsEvent(
        candidates=[
            _region(
                region_id="text",
                page=1,
                bbox_norm=(0, 0, 0.5, 0.5),
                region_type="text",
                score=0.9,
            ),
            _region(
                region_id="tbl",
                page=1,
                bbox_norm=(0.5, 0.5, 1.0, 1.0),
                region_type="table",
                score=0.65,
            ),
        ]
    )
    plan = _plan_with_evidence(["table"], max_crops=2)
    ev = await inspect_regions(
        _q(), plan, regions, images_by_page={1: tmp_path / "p.png"}, pdf_path=pdf
    )
    # table (0.65 * 1.5 = 0.975) > text (0.9).
    assert ev.packets[0].region_type == "table"


async def test_no_evidence_types_preserves_base_ranking(tmp_path, monkeypatch):
    """Empty/None evidence_types → no boost, raw score wins."""
    inspect_calls: list = []
    text_calls: list = []
    _install_fake_tools(monkeypatch, inspect_calls=inspect_calls, text_calls=text_calls)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    regions = RegionsEvent(
        candidates=[
            _region(
                region_id="text",
                page=1,
                bbox_norm=(0, 0, 0.5, 0.5),
                region_type="text",
                score=0.92,
            ),
            _region(
                region_id="pic",
                page=1,
                bbox_norm=(0.5, 0, 1.0, 1.0),
                region_type="picture",
                score=0.7,
            ),
        ]
    )
    plan = _plan_with_evidence([], max_crops=2)
    ev = await inspect_regions(
        _q(), plan, regions, images_by_page={1: tmp_path / "p.png"}, pdf_path=pdf
    )
    # Without evidence_types boost, raw score ordering stands.
    assert [p.region_type for p in ev.packets] == ["text", "picture"]


async def test_unknown_evidence_type_is_noop(tmp_path, monkeypatch):
    """Planner emits something the alias map doesn't know → no boost, no crash."""
    inspect_calls: list = []
    text_calls: list = []
    _install_fake_tools(monkeypatch, inspect_calls=inspect_calls, text_calls=text_calls)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    regions = RegionsEvent(
        candidates=[
            _region(
                region_id="text",
                page=1,
                bbox_norm=(0, 0, 0.5, 0.5),
                region_type="text",
                score=0.92,
            ),
            _region(
                region_id="pic",
                page=1,
                bbox_norm=(0.5, 0, 1.0, 1.0),
                region_type="picture",
                score=0.7,
            ),
        ]
    )
    plan = _plan_with_evidence(["schmoo_plot"], max_crops=2)  # not a known alias
    ev = await inspect_regions(
        _q(), plan, regions, images_by_page={1: tmp_path / "p.png"}, pdf_path=pdf
    )
    assert [p.region_type for p in ev.packets] == ["text", "picture"]


async def test_multiple_evidence_types_boost_each(tmp_path, monkeypatch):
    """['figure', 'table'] should boost both picture and table regions."""
    inspect_calls: list = []
    text_calls: list = []
    _install_fake_tools(monkeypatch, inspect_calls=inspect_calls, text_calls=text_calls)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    regions = RegionsEvent(
        candidates=[
            _region(
                region_id="text",
                page=1,
                bbox_norm=(0, 0, 0.3, 0.3),
                region_type="text",
                score=0.95,
            ),
            _region(
                region_id="tbl",
                page=1,
                bbox_norm=(0, 0.3, 0.3, 0.6),
                region_type="table",
                score=0.7,
            ),
            _region(
                region_id="pic",
                page=1,
                bbox_norm=(0.5, 0, 1.0, 1.0),
                region_type="picture",
                score=0.65,
            ),
        ]
    )
    plan = _plan_with_evidence(["figure", "table"], max_crops=3)
    ev = await inspect_regions(
        _q(), plan, regions, images_by_page={1: tmp_path / "p.png"}, pdf_path=pdf
    )
    # Both boosted regions rank above text: table (1.05) > picture (0.975) > text (0.95).
    assert [p.region_type for p in ev.packets] == ["table", "picture", "text"]


async def test_packet_confidence_preserves_raw_score(tmp_path, monkeypatch):
    """The boost is used for ranking only; packet.confidence keeps the raw
    detector score so downstream consumers don't see an inflated number."""
    inspect_calls: list = []
    text_calls: list = []
    _install_fake_tools(
        monkeypatch,
        inspect_calls=inspect_calls,
        text_calls=text_calls,
        inspect_element_out=None,  # use default element behavior
    )
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    regions = RegionsEvent(
        candidates=[
            _region(
                region_id="pic",
                page=1,
                bbox_norm=(0, 0, 1, 1),
                region_type="picture",
                score=0.7,
            )
        ]
    )
    ev = await inspect_regions(
        _q(),
        _plan_with_evidence(["figure"], max_crops=1),
        regions,
        images_by_page={1: tmp_path / "p.png"},
        pdf_path=pdf,
    )
    # Raw score 0.7 preserved — NOT 0.7 * 1.5 = 1.05.
    assert ev.packets[0].confidence == pytest.approx(0.7)


async def test_tool_errors_degrade_to_fallback_packet(tmp_path, monkeypatch):
    """When inspect_region and get_text_layer both raise, the packet is still
    emitted with skeleton_inspector_fallback provenance — the run keeps going."""

    async def _boom_inspect(inp, *, cache_dir=None):
        raise FileNotFoundError("simulated")

    async def _boom_text(inp, *, cache_dir=None):
        raise FileNotFoundError("simulated")

    monkeypatch.setattr("focusparse.pipeline.inspector.inspect_region", _boom_inspect)
    monkeypatch.setattr("focusparse.pipeline.inspector.get_text_layer", _boom_text)

    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    regions = RegionsEvent(
        candidates=[
            _region(
                region_id="r", page=1, bbox_norm=(0, 0, 0.5, 0.5), region_type="text", score=0.9
            )
        ]
    )
    ev = await inspect_regions(
        _q(),
        _plan(),
        regions,
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
    )
    assert len(ev.packets) == 1
    assert ev.packets[0].provenance.tool == "skeleton_inspector_fallback"


# ---------------------------------------------------------------------------
# Phase 3 auto-zoom — inspector swaps in LANCZOS-upsampled crops for tiny regions
# ---------------------------------------------------------------------------


def _bbox_with_area(area: float) -> tuple[float, float, float, float]:
    """Return a bbox with the requested normalized area (square)."""
    side = area**0.5
    return (0.1, 0.1, 0.1 + side, 0.1 + side)


async def test_auto_zoom_skips_when_disabled(tmp_path, monkeypatch):
    """auto_zoom=False (default) → run_python is never called."""
    inspect_calls: list = []
    text_calls: list = []
    run_python_calls: list = []

    async def _fake_run_python(inp, **kw):
        run_python_calls.append(inp.code)
        from focusparse.tools.run_python import RunPythonOutput

        return RunPythonOutput(stdout="ok", new_image_refs=["zoomed"])

    _install_fake_tools(monkeypatch, inspect_calls=inspect_calls, text_calls=text_calls)
    monkeypatch.setattr("focusparse.pipeline.inspector.run_python", _fake_run_python)

    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    regions = RegionsEvent(
        candidates=[
            _region(
                region_id="tiny",
                page=1,
                bbox_norm=_bbox_with_area(0.001),  # well below threshold
                region_type="text",
                score=0.9,
            )
        ]
    )
    await inspect_regions(
        _q(),
        _plan(),
        regions,
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
        # auto_zoom defaults to False
    )
    assert run_python_calls == []


async def test_auto_zoom_fires_for_tiny_region(tmp_path, monkeypatch):
    """auto_zoom=True + tiny region → run_python(zoom2x) called, packet
    crop_ref points at the upsampled PNG."""
    inspect_calls: list = []
    text_calls: list = []
    run_python_calls: list = []

    async def _fake_run_python(inp, *, image_cache_dir=None, new_image_cache_dir=None):
        run_python_calls.append(
            {
                "code": inp.code,
                "refs": list(inp.image_refs),
                "image_cache_dir": image_cache_dir,
            }
        )
        from focusparse.tools.run_python import RunPythonOutput

        return RunPythonOutput(stdout="ok", new_image_refs=["zoomed_abc"])

    _install_fake_tools(monkeypatch, inspect_calls=inspect_calls, text_calls=text_calls)
    monkeypatch.setattr("focusparse.pipeline.inspector.run_python", _fake_run_python)

    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    cache_dir = tmp_path / "crops"
    cache_dir.mkdir()
    regions = RegionsEvent(
        candidates=[
            _region(
                region_id="tiny",
                page=1,
                bbox_norm=_bbox_with_area(0.001),
                region_type="text",
                score=0.9,
            )
        ]
    )
    ev = await inspect_regions(
        _q(),
        _plan(),
        regions,
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
        crop_cache_dir=cache_dir,
        auto_zoom=True,
    )
    assert len(run_python_calls) == 1
    assert "LANCZOS" in run_python_calls[0]["code"]
    # Packet crop_ref now points at the zoomed PNG.
    packet = ev.packets[0]
    assert packet.local_crop_ref == str(cache_dir / "zoomed_abc.png")
    # Provenance reflects the zoom step.
    assert "run_python:zoom2x" in (packet.provenance.args_hash or "")


async def test_auto_zoom_skips_for_large_region(tmp_path, monkeypatch):
    """auto_zoom=True but region area above threshold → run_python NOT called."""
    inspect_calls: list = []
    text_calls: list = []
    run_python_calls: list = []

    async def _fake_run_python(inp, **kw):
        run_python_calls.append(inp.code)
        from focusparse.tools.run_python import RunPythonOutput

        return RunPythonOutput(stdout="ok", new_image_refs=["zoomed"])

    _install_fake_tools(monkeypatch, inspect_calls=inspect_calls, text_calls=text_calls)
    monkeypatch.setattr("focusparse.pipeline.inspector.run_python", _fake_run_python)

    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    regions = RegionsEvent(
        candidates=[
            _region(
                region_id="big",
                page=1,
                # 0.3×0.3 = 0.09 area, well above threshold of 0.005
                bbox_norm=(0.1, 0.1, 0.4, 0.4),
                region_type="text",
                score=0.9,
            )
        ]
    )
    await inspect_regions(
        _q(),
        _plan(),
        regions,
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
        auto_zoom=True,
    )
    assert run_python_calls == []


async def test_auto_zoom_failure_keeps_original_crop(tmp_path, monkeypatch):
    """run_python returns an error → original crop_ref is preserved."""
    inspect_calls: list = []
    text_calls: list = []

    async def _fake_run_python(inp, **kw):
        from focusparse.tools.run_python import RunPythonOutput

        return RunPythonOutput(stdout="", stderr="ImportError", exit_code=1)

    _install_fake_tools(monkeypatch, inspect_calls=inspect_calls, text_calls=text_calls)
    monkeypatch.setattr("focusparse.pipeline.inspector.run_python", _fake_run_python)

    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    regions = RegionsEvent(
        candidates=[
            _region(
                region_id="tiny",
                page=1,
                bbox_norm=_bbox_with_area(0.001),
                region_type="text",
                score=0.9,
            )
        ]
    )
    ev = await inspect_regions(
        _q(),
        _plan(),
        regions,
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
        crop_cache_dir=tmp_path / "crops",
        auto_zoom=True,
    )
    # crop_ref came from inspect_region (unchanged), not run_python.
    assert "zoomed" not in ev.packets[0].local_crop_ref
    assert "run_python:zoom2x" not in (ev.packets[0].provenance.args_hash or "")


# ---------------------------------------------------------------------------
# 2026-05-04 sprint Phase 2: multi-scale evidence packets (Phase 6 #6)
# ---------------------------------------------------------------------------


async def test_multi_scale_packets_default_off_produces_no_extra_crops(tmp_path, monkeypatch):
    """multi_scale=False (default) keeps the existing single-crop behavior;
    multi_scale_crops list stays empty so legacy traces / reasoner prompts
    don't see the new field populated."""
    inspect_calls: list = []
    text_calls: list = []
    _install_fake_tools(monkeypatch, inspect_calls=inspect_calls, text_calls=text_calls)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    regions = RegionsEvent(
        candidates=[_region(region_id="r0", page=1, bbox_norm=(0.1, 0.2, 0.5, 0.6), score=0.9)]
    )
    ev = await inspect_regions(
        _q(),
        _plan(),
        regions,
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
    )
    assert ev.packets[0].multi_scale_crops == []


async def test_multi_scale_packets_renders_tight_plus_context(tmp_path, monkeypatch):
    """multi_scale=True triggers a second inspect_region call for the
    context (30%-padded) bbox; both crops land in multi_scale_crops as
    ordered tight → context entries."""
    inspect_calls: list = []
    text_calls: list = []
    _install_fake_tools(monkeypatch, inspect_calls=inspect_calls, text_calls=text_calls)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    regions = RegionsEvent(
        candidates=[_region(region_id="r0", page=1, bbox_norm=(0.10, 0.20, 0.50, 0.60), score=0.9)]
    )
    ev = await inspect_regions(
        _q(),
        _plan(),
        regions,
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
        multi_scale=True,
    )
    pkt = ev.packets[0]
    assert len(pkt.multi_scale_crops) == 2
    assert pkt.multi_scale_crops[0].scale == "tight"
    assert pkt.multi_scale_crops[1].scale == "context"
    # Context bbox is widened from the original by 0.30 on each side.
    tight_bbox = pkt.multi_scale_crops[0].bbox_norm
    context_bbox = pkt.multi_scale_crops[1].bbox_norm
    assert tight_bbox == (0.10, 0.20, 0.50, 0.60)
    assert context_bbox[0] == pytest.approx(0.0, abs=1e-6)
    assert context_bbox[1] == pytest.approx(0.0, abs=1e-6)
    assert context_bbox[2] == pytest.approx(0.80, abs=1e-6)
    assert context_bbox[3] == pytest.approx(0.90, abs=1e-6)
    # crop_signals provenance records the second call.
    assert "inspect_region:context" in pkt.provenance.args_hash


async def test_multi_scale_skipped_when_no_pdf(tmp_path, monkeypatch):
    """multi_scale=True without a pdf_path has nothing to render — the
    packet falls back gracefully with empty multi_scale_crops."""
    inspect_calls: list = []
    text_calls: list = []
    _install_fake_tools(monkeypatch, inspect_calls=inspect_calls, text_calls=text_calls)

    regions = RegionsEvent(
        candidates=[_region(region_id="r0", page=1, bbox_norm=(0.1, 0.2, 0.5, 0.6), score=0.9)]
    )
    ev = await inspect_regions(
        _q(),
        _plan(),
        regions,
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=None,
        multi_scale=True,
    )
    assert ev.packets[0].multi_scale_crops == []


# ---------------------------------------------------------------------------
# 2026-05-04 sprint Phase 3: chart_to_table conditional (Phase 6 #7)
# ---------------------------------------------------------------------------


async def test_chart_to_table_fires_only_for_chart_question_families(tmp_path, monkeypatch):
    """chart_to_table runs when (a) the flag is on, (b) plan.question_family ∈
    {axis_value_interpolation, candlestick_ohlc_extraction}, and (c) the region
    has figure_class:bar_chart|line_chart|candlestick.

    All three conditions must hold; otherwise the helper is silent.
    """
    inspect_calls: list = []
    text_calls: list = []
    _install_fake_tools(monkeypatch, inspect_calls=inspect_calls, text_calls=text_calls)

    chart_calls: list = []

    async def _fake_chart_to_table(inp, *, crop_cache_dir=None):
        from focusparse.tools.chart_to_table import ChartToTableOutput

        chart_calls.append({"crop_ref": inp.crop_ref})
        return ChartToTableOutput(
            table_csv="x_value,y_value\n0,5\n1,10",
            confidence=0.7,
            n_points=2,
        )

    monkeypatch.setattr(
        "focusparse.tools.chart_to_table.chart_to_table",
        _fake_chart_to_table,
    )
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    chart_region = _region(
        region_id="chart0",
        page=1,
        bbox_norm=(0.1, 0.2, 0.5, 0.6),
        score=0.9,
        region_type="picture",
        supporting_signals=["figure_class:bar_chart"],
    )

    # Case 1: chart family + chart figure_class + flag on → fires.
    plan = _plan()
    plan = plan.model_copy(update={"question_family": "axis_value_interpolation"})
    ev = await inspect_regions(
        _q(),
        plan,
        RegionsEvent(candidates=[chart_region]),
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
        chart_to_table_enabled=True,
    )
    assert len(chart_calls) == 1
    assert ev.packets[0].chart_csv == "x_value,y_value\n0,5\n1,10"
    assert ev.packets[0].chart_extraction_confidence == 0.7

    # Case 2: same chart, but non-chart question family → no extraction.
    chart_calls.clear()
    plan2 = plan.model_copy(update={"question_family": "single_value_lookup"})
    ev2 = await inspect_regions(
        _q(),
        plan2,
        RegionsEvent(candidates=[chart_region]),
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
        chart_to_table_enabled=True,
    )
    assert chart_calls == []
    assert ev2.packets[0].chart_csv is None

    # Case 3: chart family but the flag is off → no extraction.
    ev3 = await inspect_regions(
        _q(),
        plan,
        RegionsEvent(candidates=[chart_region]),
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
        chart_to_table_enabled=False,
    )
    assert chart_calls == []
    assert ev3.packets[0].chart_csv is None

    # Case 4: chart family + flag on, but the region is a text region → no extraction.
    text_region = _region(
        region_id="t0",
        page=1,
        bbox_norm=(0.05, 0.10, 0.95, 0.15),
        score=0.95,
        region_type="text",
    )
    ev4 = await inspect_regions(
        _q(),
        plan,
        RegionsEvent(candidates=[text_region]),
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
        chart_to_table_enabled=True,
    )
    assert chart_calls == []
    assert ev4.packets[0].chart_csv is None
