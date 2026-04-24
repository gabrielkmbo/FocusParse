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
) -> RegionCandidate:
    return RegionCandidate(
        region_id=region_id,
        page=page,
        bbox_norm=bbox_norm,
        region_type=region_type,
        score=score,
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
