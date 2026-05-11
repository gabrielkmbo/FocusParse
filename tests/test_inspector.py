"""Tests for `focusparse.pipeline.inspector.inspect_regions` (sub-phase 2g).

Covers the smart-deterministic tool dispatcher:
  * budget: plan.max_crops caps how many regions get inspected
  * ranking: higher-score regions go first
  * visual regions (picture/chart) get crop plus advisory OCR
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
from focusparse.pipeline.inspector import (
    _AUTOZOOM_CODE,
    _AUTOZOOM_MAX_DIM,
    _chart_scale_hint,
    inspect_regions,
)


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


def _write_page_png(path, *, size=(200, 100)):
    from PIL import Image, ImageDraw

    img = Image.new("RGB", size, "white")
    ImageDraw.Draw(img).text((10, 10), "hello", fill="black")
    img.save(path)


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


async def test_multi_region_inspection_preserves_page_coverage(tmp_path, monkeypatch):
    """Multi-region plans reserve room for each routed page before filling top-N."""
    inspect_calls: list = []
    text_calls: list = []
    _install_fake_tools(monkeypatch, inspect_calls=inspect_calls, text_calls=text_calls)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    regions = RegionsEvent(
        candidates=[
            _region(region_id="p1_a", page=1, bbox_norm=(0, 0, 0.1, 0.1), score=0.99),
            _region(region_id="p1_b", page=1, bbox_norm=(0, 0, 0.2, 0.2), score=0.98),
            _region(region_id="p1_c", page=1, bbox_norm=(0, 0, 0.3, 0.3), score=0.97),
            _region(region_id="p2_a", page=2, bbox_norm=(0, 0, 0.4, 0.4), score=0.50),
        ]
    )
    plan = _plan(max_crops=3).model_copy(update={"budget_class": "multi_region"})

    ev = await inspect_regions(
        _q(),
        plan,
        regions,
        images_by_page={1: tmp_path / "p1.png", 2: tmp_path / "p2.png"},
        pdf_path=pdf,
    )

    assert [p.page for p in ev.packets] == [1, 2, 1]


# ---------------------------------------------------------------------------
# Per-region-type routing
# ---------------------------------------------------------------------------


async def test_visual_region_gets_advisory_ocr(tmp_path, monkeypatch):
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
    # Visual packets still skip native text extraction, but now get an
    # advisory element-mode OCR pass for embedded labels/callouts.
    assert [c["mode"] for c in inspect_calls] == ["image", "element"]
    assert text_calls == []
    packet = ev.packets[0]
    assert packet.ocr_snippet == "OCR TEXT"
    assert packet.text_layer_snippet is None
    assert packet.commit_level == "image"
    assert packet.confidence == pytest.approx(0.9)
    assert packet.provenance.mode == "visual"
    assert "inspect_region:element" in packet.provenance.args_hash


async def test_chart_curve_region_is_treated_as_visual(tmp_path, monkeypatch):
    inspect_calls: list = []
    text_calls: list = []
    _install_fake_tools(monkeypatch, inspect_calls=inspect_calls, text_calls=text_calls)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    regions = RegionsEvent(
        candidates=[
            _region(
                region_id="curve",
                page=1,
                bbox_norm=(0, 0, 0.5, 0.5),
                region_type="curve",
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
    assert [c["mode"] for c in inspect_calls] == ["image", "element"]
    assert text_calls == []
    packet = ev.packets[0]
    assert packet.commit_level == "image"
    assert packet.provenance.mode == "visual"


async def test_legend_and_axis_label_regions_get_text_extraction(tmp_path, monkeypatch):
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
            _region(
                region_id="legend",
                page=1,
                bbox_norm=(0, 0, 0.4, 0.2),
                region_type="legend",
                score=0.9,
            ),
            _region(
                region_id="axis",
                page=1,
                bbox_norm=(0, 0.2, 0.4, 0.4),
                region_type="axis_label",
                score=0.8,
            ),
        ]
    )
    ev = await inspect_regions(
        _q(),
        _plan(max_crops=2),
        regions,
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
    )
    assert [c["mode"] for c in inspect_calls] == ["image", "element", "image", "element"]
    assert [tuple(c["bbox_norm"]) for c in text_calls] == [
        (0.0, 0.0, 0.4, 0.2),
        (0.0, 0.2, 0.4, 0.4),
    ]
    assert [p.commit_level for p in ev.packets] == ["element", "element"]


async def test_structured_text_detector_labels_get_text_extraction(tmp_path, monkeypatch):
    inspect_calls: list = []
    text_calls: list = []
    _install_fake_tools(
        monkeypatch,
        inspect_calls=inspect_calls,
        text_calls=text_calls,
        text_layer_out=_FakeTextLayerOutput(text="", source="empty_native"),
        inspect_element_out=_FakeInspectOutput(
            crop_ref="/crops/p1_element.png", ocr_text="STRUCTURED TEXT", confidence=0.81
        ),
    )
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    labels = ["Key-Value Region", "Code", "Document Index"]
    regions = RegionsEvent(
        candidates=[
            _region(
                region_id=f"r{idx}",
                page=1,
                bbox_norm=(0.1 * idx, 0.0, 0.1 * idx + 0.08, 0.2),
                region_type=label,
                score=0.9 - (idx * 0.01),
            )
            for idx, label in enumerate(labels)
        ]
    )

    ev = await inspect_regions(
        _q(),
        _plan(max_crops=3).model_copy(update={"evidence_types": ["text"]}),
        regions,
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
    )

    assert len(text_calls) == 3
    assert [c["mode"] for c in inspect_calls] == [
        "image",
        "element",
        "image",
        "element",
        "image",
        "element",
    ]
    assert [p.ocr_snippet for p in ev.packets] == ["STRUCTURED TEXT"] * 3
    assert all("inspect_region:element" in p.provenance.args_hash for p in ev.packets)


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


async def test_pdf_path_uses_crop_fallback_ocr_when_element_ocr_empty(tmp_path, monkeypatch):
    """If element-mode OCR yields no text, use OCR on the staged crop as a fallback."""
    inspect_calls: list = []
    text_calls: list = []
    _install_fake_tools(
        monkeypatch,
        inspect_calls=inspect_calls,
        text_calls=text_calls,
        text_layer_out=_FakeTextLayerOutput(text="", source="empty_native"),
        inspect_element_out=_FakeInspectOutput(crop_ref="/c.png", ocr_text="", confidence=0.0),
    )
    monkeypatch.setattr(
        "focusparse.pipeline.inspector._ocr_existing_crop",
        lambda crop_path: ("FALLBACK OCR", 0.61),
    )
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    regions = RegionsEvent(
        candidates=[
            _region(
                region_id="fallback",
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
    assert packet.ocr_snippet == "FALLBACK OCR"
    assert packet.confidence == pytest.approx(0.61)
    assert "inspect_region:crop_fallback_ocr" in packet.provenance.args_hash


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


async def test_no_pdf_path_crops_page_image_when_available(tmp_path, monkeypatch):
    """Without a PDF, inspect can still crop the staged page PNG and OCR it."""
    inspect_calls: list = []
    text_calls: list = []
    _install_fake_tools(monkeypatch, inspect_calls=inspect_calls, text_calls=text_calls)
    monkeypatch.setattr(
        "focusparse.pipeline.inspector._ocr_existing_crop",
        lambda crop_path: ("OCR FROM PAGE IMAGE", 0.77),
    )
    page_image = tmp_path / "p1.png"
    _write_page_png(page_image)

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
        images_by_page={1: page_image},
        pdf_path=None,
    )
    assert inspect_calls == []
    assert text_calls == []
    packet = ev.packets[0]
    assert packet.provenance.tool == "deterministic_inspector"
    assert packet.local_crop_ref != str(page_image)
    assert packet.page_thumbnail_ref == str(page_image)
    assert packet.ocr_snippet == "OCR FROM PAGE IMAGE"
    assert packet.confidence == pytest.approx(0.77)
    assert "page_image_crop:image" in packet.provenance.args_hash
    assert "page_image_crop:ocr" in packet.provenance.args_hash


async def test_no_pdf_missing_page_image_produces_fallback_packets(tmp_path, monkeypatch):
    """If both PDF and staged image are missing, preserve the old skeleton packet."""
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
    missing_image = tmp_path / "p1.png"
    ev = await inspect_regions(
        _q(),
        _plan(),
        regions,
        images_by_page={1: missing_image},
        pdf_path=None,
    )
    assert inspect_calls == []
    assert text_calls == []
    packet = ev.packets[0]
    assert packet.provenance.tool == "skeleton_inspector_fallback"
    assert packet.local_crop_ref == str(missing_image)


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


async def test_chart_question_prefers_chart_subclass_over_generic_pictures(tmp_path, monkeypatch):
    """For chart-reading plans, a lower-confidence line_chart is better
    evidence than high-confidence logos or generic picture containers."""
    inspect_calls: list = []
    text_calls: list = []
    _install_fake_tools(monkeypatch, inspect_calls=inspect_calls, text_calls=text_calls)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    regions = RegionsEvent(
        candidates=[
            _region(
                region_id="logo",
                page=1,
                bbox_norm=(0.0, 0.0, 0.2, 0.1),
                region_type="picture",
                score=0.95,
                supporting_signals=["figure_class=logo"],
            ),
            _region(
                region_id="full_panel",
                page=1,
                bbox_norm=(0.0, 0.1, 1.0, 0.9),
                region_type="picture",
                score=0.90,
                supporting_signals=["figure_class=other"],
            ),
            _region(
                region_id="plot",
                page=1,
                bbox_norm=(0.2, 0.2, 0.7, 0.7),
                region_type="picture",
                score=0.62,
                supporting_signals=["figure_class=line_chart"],
            ),
        ]
    )

    ev = await inspect_regions(
        _q(),
        _plan_with_evidence(["chart"], max_crops=3),
        regions,
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
    )
    assert ev.packets[0].bbox_norm == (0.2, 0.2, 0.7, 0.7)


async def test_chart_packet_order_uses_ocr_question_overlap(tmp_path, monkeypatch):
    """After OCR, chart packets mentioning the asked series/unit should appear
    before adjacent chart packets with higher detector score but wrong labels."""
    text_calls: list = []

    async def _fake_inspect(inp, *, cache_dir=None):
        if inp.mode == "image":
            return _FakeInspectOutput(
                crop_ref=f"/crops/{inp.bbox_norm[0]}_image.png", ocr_text=None
            )
        if inp.bbox_norm[0] < 0.2:
            return _FakeInspectOutput(
                crop_ref=f"/crops/{inp.bbox_norm[0]}_element.png",
                ocr_text="Figure 32. Large-Signal Step Response 50mV/div",
                confidence=0.85,
            )
        return _FakeInspectOutput(
            crop_ref=f"/crops/{inp.bbox_norm[0]}_element.png",
            ocr_text="Figure 31. Large-Signal Step Response V_OUT (400mV/div)",
            confidence=0.85,
        )

    async def _fake_text_layer(inp, *, cache_dir=None):
        text_calls.append(inp)
        return _FakeTextLayerOutput(text="")

    monkeypatch.setattr("focusparse.pipeline.inspector.inspect_region", _fake_inspect)
    monkeypatch.setattr("focusparse.pipeline.inspector.get_text_layer", _fake_text_layer)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    regions = RegionsEvent(
        candidates=[
            _region(
                region_id="wrong_chart",
                page=1,
                bbox_norm=(0.1, 0.1, 0.4, 0.4),
                region_type="picture",
                score=0.90,
                supporting_signals=["figure_class=line_chart"],
            ),
            _region(
                region_id="matching_chart",
                page=1,
                bbox_norm=(0.2, 0.2, 0.5, 0.5),
                region_type="picture",
                score=0.80,
                supporting_signals=["figure_class=line_chart"],
            ),
        ]
    )
    question = _q().model_copy(
        update={"question": "Estimate the minimum V_OUT value in millivolts."}
    )

    ev = await inspect_regions(
        question,
        _plan_with_evidence(["chart"], max_crops=2),
        regions,
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
    )
    assert ev.packets[0].bbox_norm == (0.2, 0.2, 0.5, 0.5)


def test_chart_scale_hint_extracts_oscilloscope_scales() -> None:
    hint = _chart_scale_hint(
        "Figure 31. Large-Signal Step Response Vour (400mV/div) Viny (200mV/div) Time (2.5us/div)"
    )
    assert hint == ("Detected chart scales: VOUT=400mV/div; VIN=200mV/div; TIME=2.5us/div.")


def test_chart_scale_hint_calls_out_question_target_scale() -> None:
    hint = _chart_scale_hint(
        "Figure 31. Viny (200mV/div) Vour (400mV/div) Time (2.5us/div)",
        question_text="Estimate the minimum V_OUT value in millivolts.",
    )
    assert hint == (
        "Detected chart scales: VIN=200mV/div; VOUT=400mV/div; "
        "TIME=2.5us/div. Question target scale: VOUT=400mV/div. "
        "For waveform values, count vertical divisions from the plot's "
        "zero/reference gridline using the target curve's scale."
    )


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


def _run_autozoom_code(size: tuple[int, int]) -> tuple[int, int]:
    from PIL import Image

    saved: list[Image.Image] = []
    namespace = {
        "images": {"input": Image.new("RGB", size, "white")},
        "save_image": saved.append,
    }
    exec(_AUTOZOOM_CODE, namespace)  # noqa: S102 - exercises our sandbox payload string
    assert len(saved) == 1
    return saved[0].size


def test_autozoom_code_doubles_small_crops():
    assert _run_autozoom_code((320, 180)) == (640, 360)


def test_autozoom_code_caps_large_retry_crops():
    width, height = _run_autozoom_code((1250, 1667))
    assert max(width, height) == _AUTOZOOM_MAX_DIM
    assert (width, height) == (1536, 2048)


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
    """auto_zoom=True + tiny region → run_python(zoom2x) called. As of
    2026-05-05 (Phase B2), the zoomed crop is ADDED to multi_scale_crops
    rather than replacing local_crop_ref so the reasoner sees both the
    original tight crop and the upsampled crop side-by-side."""
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
    packet = ev.packets[0]
    # local_crop_ref keeps the ORIGINAL tight crop (no longer replaced).
    assert packet.local_crop_ref != str(cache_dir / "zoomed_abc.png")
    # The zoomed crop is appended to multi_scale_crops with scale="zoomed".
    zoom_entries = [c for c in packet.multi_scale_crops if c.scale == "zoomed"]
    assert len(zoom_entries) == 1
    assert zoom_entries[0].ref == str(cache_dir / "zoomed_abc.png")
    # Multi-scale also seeds element 0 = tight (mirrors local_crop_ref).
    tight_entries = [c for c in packet.multi_scale_crops if c.scale == "tight"]
    assert len(tight_entries) == 1
    assert tight_entries[0].ref == packet.local_crop_ref
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


async def test_auto_zoom_fires_on_fine_detail_question_family(tmp_path, monkeypatch):
    """2026-05-05 (Phase B2): auto_zoom now also fires when the question
    asks for fine-detail reading, even on regions LARGER than the tiny
    threshold. axis_value_interpolation / confusable_label / etc. all
    benefit from a 2× upsample regardless of crop size."""
    inspect_calls: list = []
    text_calls: list = []
    run_python_calls: list = []

    async def _fake_run_python(inp, *, image_cache_dir=None, new_image_cache_dir=None):
        run_python_calls.append({"code": inp.code})
        from focusparse.tools.run_python import RunPythonOutput

        return RunPythonOutput(stdout="ok", new_image_refs=["zoomed_axis"])

    _install_fake_tools(monkeypatch, inspect_calls=inspect_calls, text_calls=text_calls)
    monkeypatch.setattr("focusparse.pipeline.inspector.run_python", _fake_run_python)

    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    cache_dir = tmp_path / "crops"
    cache_dir.mkdir()

    # Region is well above the tiny threshold (0.3×0.3 = 0.09 area), but
    # the question is axis_value_interpolation — fine-detail reading.
    regions = RegionsEvent(
        candidates=[
            _region(
                region_id="big_chart",
                page=1,
                bbox_norm=(0.10, 0.10, 0.40, 0.40),
                region_type="picture",
                score=0.9,
            )
        ]
    )
    plan_with_fine_detail = _plan().model_copy(
        update={"question_family": "axis_value_interpolation"}
    )
    ev = await inspect_regions(
        _q(),
        plan_with_fine_detail,
        regions,
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
        crop_cache_dir=cache_dir,
        auto_zoom=True,
    )
    # run_python was called even though the region is large.
    assert len(run_python_calls) == 1
    packet = ev.packets[0]
    zoom_entries = [c for c in packet.multi_scale_crops if c.scale == "zoomed"]
    assert len(zoom_entries) == 1
    # Provenance tag includes the question_family that unlocked the zoom.
    assert "run_python:zoom2x@axis_value_interpolation" in (packet.provenance.args_hash or "")


async def test_auto_zoom_skips_when_neither_tiny_nor_fine_detail(tmp_path, monkeypatch):
    """auto_zoom=True but bbox is large AND question_family isn't fine-detail
    → run_python not called (the original tiny-only behavior)."""
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
                bbox_norm=(0.1, 0.1, 0.4, 0.4),  # 0.09 area, large
                region_type="text",
                score=0.9,
            )
        ]
    )
    plan_generic = _plan().model_copy(update={"question_family": "single_value_lookup"})
    await inspect_regions(
        _q(),
        plan_generic,
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


async def test_chart_extraction_adds_chart_context_crop_without_multi_scale(tmp_path, monkeypatch):
    """Chart extraction gets a modest context crop even when the larger
    multi_scale experiment is off. This gives visual chart reads nearby axes
    without enabling broad 30%-padded context on every packet."""
    inspect_calls: list = []
    text_calls: list = []
    _install_fake_tools(monkeypatch, inspect_calls=inspect_calls, text_calls=text_calls)

    chart_calls: list = []

    async def _fake_chart_to_table(inp, *, crop_cache_dir=None):
        from focusparse.tools.chart_to_table import ChartToTableOutput

        chart_calls.append({"crop_ref": inp.crop_ref})
        return ChartToTableOutput(table_csv="", confidence=0.0, n_points=0)

    monkeypatch.setattr(
        "focusparse.tools.chart_to_table.chart_to_table",
        _fake_chart_to_table,
    )

    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    chart_region = _region(
        region_id="chart0",
        page=1,
        bbox_norm=(0.20, 0.30, 0.50, 0.60),
        score=0.9,
        region_type="picture",
        supporting_signals=["figure_class=line_chart"],
    )
    plan = _plan().model_copy(
        update={
            "question_family": "curve_axis_reading",
            "evidence_types": ["chart"],
        }
    )

    ev = await inspect_regions(
        _q(),
        plan,
        RegionsEvent(candidates=[chart_region]),
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
        chart_to_table_enabled=True,
        multi_scale=False,
    )

    pkt = ev.packets[0]
    assert len(chart_calls) == 1
    assert len(pkt.multi_scale_crops) == 2
    assert pkt.multi_scale_crops[0].scale == "tight"
    assert pkt.multi_scale_crops[0].bbox_norm == (0.20, 0.30, 0.50, 0.60)
    assert pkt.multi_scale_crops[1].scale == "chart_context"
    assert pkt.multi_scale_crops[1].bbox_norm == pytest.approx(
        (0.08, 0.18, 0.62, 0.72),
        abs=1e-6,
    )
    assert "inspect_region:chart_context" in pkt.provenance.args_hash
    assert "chart_to_table:attempt" in pkt.provenance.args_hash
    assert "chart_to_table:empty" in pkt.provenance.args_hash

    image_calls = [call for call in inspect_calls if call["mode"] == "image"]
    assert tuple(image_calls[0]["bbox_norm"]) == (0.20, 0.30, 0.50, 0.60)
    assert tuple(image_calls[1]["bbox_norm"]) == pytest.approx(
        (0.08, 0.18, 0.62, 0.72),
        abs=1e-6,
    )


async def test_chart_question_adds_context_crop_without_chart_to_table(tmp_path, monkeypatch):
    """The lightweight chart-context crop is useful even when the heavier
    chart_to_table helper is disabled for the headline +4 path."""
    inspect_calls: list = []
    text_calls: list = []
    _install_fake_tools(monkeypatch, inspect_calls=inspect_calls, text_calls=text_calls)

    chart_calls: list = []

    async def _fake_chart_to_table(inp, *, crop_cache_dir=None):
        chart_calls.append({"crop_ref": inp.crop_ref})
        raise AssertionError("chart_to_table should stay disabled")

    monkeypatch.setattr(
        "focusparse.tools.chart_to_table.chart_to_table",
        _fake_chart_to_table,
    )

    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    chart_region = _region(
        region_id="chart0",
        page=1,
        bbox_norm=(0.20, 0.30, 0.50, 0.60),
        score=0.9,
        region_type="picture",
        supporting_signals=["figure_class=line_chart"],
    )
    plan = _plan().model_copy(
        update={
            "question_family": "axis_value_interpolation",
            "evidence_types": ["chart"],
        }
    )

    ev = await inspect_regions(
        _q(),
        plan,
        RegionsEvent(candidates=[chart_region]),
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
        chart_to_table_enabled=False,
        multi_scale=False,
    )

    pkt = ev.packets[0]
    assert chart_calls == []
    assert len(pkt.multi_scale_crops) == 2
    assert pkt.multi_scale_crops[0].scale == "tight"
    assert pkt.multi_scale_crops[1].scale == "chart_context"
    assert "inspect_region:chart_context" in pkt.provenance.args_hash
    assert "chart_to_table:attempt" not in pkt.provenance.args_hash


async def test_timing_diagram_adds_visual_context_crop_without_multi_scale(tmp_path, monkeypatch):
    """Timing questions get a modest same-packet context crop by default."""
    inspect_calls: list = []
    text_calls: list = []
    _install_fake_tools(monkeypatch, inspect_calls=inspect_calls, text_calls=text_calls)

    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    timing_region = _region(
        region_id="timing0",
        page=1,
        bbox_norm=(0.20, 0.30, 0.50, 0.60),
        score=0.9,
        region_type="picture",
        supporting_signals=["figure_class=timing_diagram"],
    )
    plan = _plan().model_copy(
        update={
            "question_family": "timing_diagram_reading",
            "evidence_types": ["figure"],
        }
    )

    ev = await inspect_regions(
        _q(),
        plan,
        RegionsEvent(candidates=[timing_region]),
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
        chart_to_table_enabled=False,
        multi_scale=False,
    )

    pkt = ev.packets[0]
    assert len(pkt.multi_scale_crops) == 2
    assert pkt.multi_scale_crops[0].scale == "tight"
    assert pkt.multi_scale_crops[1].scale == "context"
    assert pkt.multi_scale_crops[1].bbox_norm == pytest.approx(
        (0.04, 0.14, 0.66, 0.76),
        abs=1e-6,
    )
    assert "inspect_region:visual_context" in pkt.provenance.args_hash

    image_calls = [call for call in inspect_calls if call["mode"] == "image"]
    assert tuple(image_calls[1]["bbox_norm"]) == pytest.approx(
        (0.04, 0.14, 0.66, 0.76),
        abs=1e-6,
    )


async def test_multi_chart_context_crops_are_limited_to_top_visual_packets(tmp_path, monkeypatch):
    """Broad chart-comparison questions should not add context to every panel."""
    inspect_calls: list = []
    text_calls: list = []
    _install_fake_tools(monkeypatch, inspect_calls=inspect_calls, text_calls=text_calls)

    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    regions = [
        _region(
            region_id=f"chart{i}",
            page=1,
            bbox_norm=(0.10, 0.10 + i * 0.20, 0.40, 0.25 + i * 0.20),
            score=0.9 - i * 0.01,
            region_type="picture",
            supporting_signals=["figure_class=line_chart"],
        )
        for i in range(3)
    ]
    plan = _plan().model_copy(
        update={
            "question_family": "multi_chart_comparison",
            "evidence_types": ["chart", "legend"],
        }
    )

    ev = await inspect_regions(
        _q(),
        plan,
        RegionsEvent(candidates=regions),
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
        chart_to_table_enabled=False,
        multi_scale=False,
    )

    assert [bool(p.multi_scale_crops) for p in ev.packets] == [True, True, False]
    assert [p.multi_scale_crops[-1].scale if p.multi_scale_crops else None for p in ev.packets] == [
        "chart_context",
        "chart_context",
        None,
    ]


async def test_legend_series_context_crop_skips_weak_rerank_signal(tmp_path, monkeypatch):
    """If reranker scored a broad legend packet weakly, keep it single-scale."""
    inspect_calls: list = []
    text_calls: list = []
    _install_fake_tools(monkeypatch, inspect_calls=inspect_calls, text_calls=text_calls)

    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    weak_region = RegionCandidate(
        region_id="legend-panel",
        page=1,
        bbox_norm=(0.20, 0.30, 0.50, 0.60),
        score=0.95,
        region_type="picture",
        relevance=0.4,
    )
    plan = _plan().model_copy(
        update={
            "question_family": "legend_series_binding",
            "evidence_types": ["figure", "legend"],
        }
    )

    ev = await inspect_regions(
        _q(),
        plan,
        RegionsEvent(candidates=[weak_region]),
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
        chart_to_table_enabled=False,
        multi_scale=False,
    )

    pkt = ev.packets[0]
    assert pkt.multi_scale_crops == []
    assert "visual_context" not in pkt.provenance.args_hash


async def test_generic_visual_question_does_not_add_visual_context_crop(tmp_path, monkeypatch):
    """The proactive context crop is family-gated, not a global image-budget bump."""
    inspect_calls: list = []
    text_calls: list = []
    _install_fake_tools(monkeypatch, inspect_calls=inspect_calls, text_calls=text_calls)

    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    visual_region = _region(
        region_id="pic0",
        page=1,
        bbox_norm=(0.20, 0.30, 0.50, 0.60),
        score=0.9,
        region_type="picture",
    )

    ev = await inspect_regions(
        _q(),
        _plan().model_copy(update={"question_family": "single_value_lookup"}),
        RegionsEvent(candidates=[visual_region]),
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
        chart_to_table_enabled=False,
        multi_scale=False,
    )

    pkt = ev.packets[0]
    assert pkt.multi_scale_crops == []
    assert "visual_context" not in pkt.provenance.args_hash
    assert len([call for call in inspect_calls if call["mode"] == "image"]) == 1


async def test_chart_context_crop_dropped_when_target_scale_is_already_visible(
    tmp_path, monkeypatch
):
    """If OCR already exposes the requested per-division scale, keep the
    packet tight so adjacent charts do not distract visual interpolation."""
    inspect_calls: list = []
    text_calls: list = []
    _install_fake_tools(
        monkeypatch,
        inspect_calls=inspect_calls,
        text_calls=text_calls,
        inspect_element_out=_FakeInspectOutput(
            crop_ref="/crops/p1_element.png",
            ocr_text="Figure 31. Vout (400mV/div) Time (2.5us/div)",
            confidence=0.85,
        ),
    )

    async def _fake_chart_to_table(inp, *, crop_cache_dir=None):
        from focusparse.tools.chart_to_table import ChartToTableOutput

        return ChartToTableOutput(table_csv="", confidence=0.0, n_points=0)

    monkeypatch.setattr(
        "focusparse.tools.chart_to_table.chart_to_table",
        _fake_chart_to_table,
    )

    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    chart_region = _region(
        region_id="chart0",
        page=1,
        bbox_norm=(0.20, 0.30, 0.50, 0.60),
        score=0.9,
        region_type="picture",
        supporting_signals=["figure_class=line_chart"],
    )
    plan = _plan().model_copy(
        update={
            "question_family": "axis_value_interpolation",
            "evidence_types": ["chart"],
        }
    )
    question = _q().model_copy(
        update={"question": "Estimate the minimum V_OUT value in millivolts."}
    )

    ev = await inspect_regions(
        question,
        plan,
        RegionsEvent(candidates=[chart_region]),
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
        chart_to_table_enabled=True,
        multi_scale=False,
    )

    pkt = ev.packets[0]
    assert pkt.multi_scale_crops == []
    assert "Question target scale: VOUT=400mV/div" in pkt.ocr_snippet
    assert "inspect_region:chart_context" not in pkt.provenance.args_hash
    assert [call["mode"] for call in inspect_calls].count("image") == 2


# ---------------------------------------------------------------------------
# 2026-05-04 sprint Phase 3: chart_to_table conditional (Phase 6 #7)
# ---------------------------------------------------------------------------


async def test_chart_to_table_fires_only_for_chart_question_families(tmp_path, monkeypatch):
    """chart_to_table runs when (a) the flag is on, (b) plan.question_family ∈
    `_CHART_QUESTION_FAMILIES` (expanded 2026-05-11 to cover the planner's
    finance chart-bearing families) or plan.evidence_types contains chart,
    and (c) the region has figure_class=bar_chart|line_chart|candlestick
    (or legacy colon form).

    All three conditions must hold; otherwise the helper is silent.
    """
    inspect_calls: list = []
    text_calls: list = []
    _install_fake_tools(
        monkeypatch,
        inspect_calls=inspect_calls,
        text_calls=text_calls,
        inspect_element_out=_FakeInspectOutput(
            crop_ref="/crops/p1_element.png",
            ocr_text="Figure 31. Vour (400mV/div) Time (2.5us/div)",
            confidence=0.85,
        ),
    )

    chart_calls: list = []
    chart_output = {
        "table_csv": "x_value,y_value\n0,5\n1,10",
        "confidence": 0.7,
        "n_points": 2,
    }

    async def _fake_chart_to_table(inp, *, crop_cache_dir=None):
        from focusparse.tools.chart_to_table import ChartToTableOutput

        chart_calls.append({"crop_ref": inp.crop_ref})
        return ChartToTableOutput(
            table_csv=chart_output["table_csv"],
            confidence=chart_output["confidence"],
            n_points=chart_output["n_points"],
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
    assert "chart_to_table:attempt" in ev.packets[0].provenance.args_hash
    assert "chart_to_table:n=2" in ev.packets[0].provenance.args_hash
    assert ev.packets[0].ocr_snippet.startswith("Chart packet: figure_class=bar_chart")
    assert "chart_to_table=csv(2 points)" in ev.packets[0].ocr_snippet

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

    # Case 2b: a planner family miss can still fire when evidence_types asks for charts.
    chart_calls.clear()
    plan2b = plan2.model_copy(update={"evidence_types": ["chart"]})
    ev2b = await inspect_regions(
        _q(),
        plan2b,
        RegionsEvent(candidates=[chart_region]),
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
        chart_to_table_enabled=True,
    )
    assert len(chart_calls) == 1
    assert ev2b.packets[0].chart_csv == "x_value,y_value\n0,5\n1,10"

    # Case 3: chart family but the flag is off → no extraction.
    chart_calls.clear()
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

    # Case 4: live localizer signal form uses figure_class=<name> and should fire.
    chart_calls.clear()
    chart_region_equals = chart_region.model_copy(
        update={"supporting_signals": ["figure_class=line_chart"]}
    )
    ev4 = await inspect_regions(
        _q(),
        plan,
        RegionsEvent(candidates=[chart_region_equals]),
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
        chart_to_table_enabled=True,
    )
    assert len(chart_calls) == 1
    assert ev4.packets[0].chart_csv == "x_value,y_value\n0,5\n1,10"
    assert "chart_to_table:attempt" in ev4.packets[0].provenance.args_hash

    # Case 5: attempted chart extraction that yields no table is visible in provenance.
    chart_calls.clear()
    chart_output.update({"table_csv": "", "confidence": 0.0, "n_points": 0})
    ev5 = await inspect_regions(
        _q(),
        plan,
        RegionsEvent(candidates=[chart_region_equals]),
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
        chart_to_table_enabled=True,
    )
    assert len(chart_calls) == 1
    assert ev5.packets[0].chart_csv is None
    assert ev5.packets[0].chart_extraction_confidence == 0.0
    assert "chart_to_table:attempt" in ev5.packets[0].provenance.args_hash
    assert "chart_to_table:empty" in ev5.packets[0].provenance.args_hash
    assert "chart_to_table=empty" in ev5.packets[0].ocr_snippet
    assert "Detected chart scales: VOUT=400mV/div" in ev5.packets[0].ocr_snippet

    # Case 6: chart family + flag on, but the region is a text region → no extraction.
    chart_calls.clear()
    text_region = _region(
        region_id="t0",
        page=1,
        bbox_norm=(0.05, 0.10, 0.95, 0.15),
        score=0.95,
        region_type="text",
    )
    ev6 = await inspect_regions(
        _q(),
        plan,
        RegionsEvent(candidates=[text_region]),
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
        chart_to_table_enabled=True,
    )
    assert chart_calls == []
    assert ev6.packets[0].chart_csv is None


# ---------------------------------------------------------------------------
# 2026-05-11 harness-growth Phase 1: chart_to_table gate expansion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "family",
    [
        # Newly added 2026-05-11 — must fire chart_to_table for these too.
        "chart_table_cross_ref",
        "legend_series_binding",
        "multi_chart_comparison",
        "chart_caption_fusion",
        "chart_footnote_fusion",
        "dual_axis_disambiguation",
    ],
)
async def test_chart_to_table_fires_for_expanded_finance_families(family, tmp_path, monkeypatch):
    """Phase 1 of harness-growth-sprint expanded `_CHART_QUESTION_FAMILIES`
    to include the planner's full set of chart-bearing finance families.

    Finance is the weak domain in the headline (32-43% vs 50% datasheets) and
    most finance failures are chart-table cross-references. The gate stays
    safe because `_region_is_chart(region)` still has to be true — non-chart
    regions cannot trigger extraction even if their family is listed.
    """
    _install_fake_tools(monkeypatch, inspect_calls=[], text_calls=[])

    chart_calls: list = []

    async def _fake_chart_to_table(inp, *, crop_cache_dir=None):
        from focusparse.tools.chart_to_table import ChartToTableOutput

        chart_calls.append({"crop_ref": inp.crop_ref, "family": family})
        return ChartToTableOutput(
            table_csv="x_value,y_value\n0,1\n1,2",
            confidence=0.6,
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
        bbox_norm=(0.10, 0.20, 0.50, 0.60),
        score=0.9,
        region_type="picture",
        supporting_signals=["figure_class=line_chart"],
    )
    plan = _plan().model_copy(update={"question_family": family})

    ev = await inspect_regions(
        _q(),
        plan,
        RegionsEvent(candidates=[chart_region]),
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
        chart_to_table_enabled=True,
    )

    assert len(chart_calls) == 1, f"chart_to_table did not fire for family={family!r}"
    assert ev.packets[0].chart_csv == "x_value,y_value\n0,1\n1,2"


async def test_chart_to_table_skipped_for_non_chart_family_even_with_flag(tmp_path, monkeypatch):
    """Non-chart families must NOT trigger chart_to_table even when the flag is
    on. Guards against accidental over-expansion of `_CHART_QUESTION_FAMILIES`."""
    _install_fake_tools(monkeypatch, inspect_calls=[], text_calls=[])
    chart_calls: list = []

    async def _fake_chart_to_table(inp, *, crop_cache_dir=None):
        from focusparse.tools.chart_to_table import ChartToTableOutput

        chart_calls.append({"crop_ref": inp.crop_ref})
        return ChartToTableOutput(table_csv="x,y\n0,0", confidence=0.5, n_points=1)

    monkeypatch.setattr(
        "focusparse.tools.chart_to_table.chart_to_table",
        _fake_chart_to_table,
    )

    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    chart_region = _region(
        region_id="chart0",
        page=1,
        bbox_norm=(0.10, 0.20, 0.50, 0.60),
        score=0.9,
        region_type="picture",
        supporting_signals=["figure_class=line_chart"],
    )

    # `spec_table_cell_retrieval` is a datasheet family with no chart involvement.
    plan = _plan().model_copy(
        update={"question_family": "spec_table_cell_retrieval", "evidence_types": ["table"]}
    )

    ev = await inspect_regions(
        _q(),
        plan,
        RegionsEvent(candidates=[chart_region]),
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
        chart_to_table_enabled=True,
    )
    assert chart_calls == [], "chart_to_table fired on a non-chart family — gate was over-expanded"
    assert ev.packets[0].chart_csv is None


# ---------------------------------------------------------------------------
# 2026-05-05 sprint Phase B3: inspector ranker respects reranker relevance
# ---------------------------------------------------------------------------


async def test_rank_score_uses_reranker_relevance(tmp_path, monkeypatch):
    """A high-relevance region (rerank=0.9) outranks a higher detector-score
    region with no rerank signal — the reranker is the better query-conditioned
    signal."""
    inspect_calls: list = []
    text_calls: list = []
    _install_fake_tools(monkeypatch, inspect_calls=inspect_calls, text_calls=text_calls)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    high_rerank_low_score = RegionCandidate(
        region_id="high_rerank",
        page=1,
        bbox_norm=(0.05, 0.05, 0.40, 0.30),
        region_type="picture",
        score=0.55,  # mediocre detector confidence
        relevance=0.95,  # but rerank says it's almost certainly the answer
    )
    high_score_no_rerank = RegionCandidate(
        region_id="high_score",
        page=1,
        bbox_norm=(0.50, 0.50, 0.90, 0.90),
        region_type="text",
        score=0.95,  # high detector confidence
        relevance=None,  # rerank didn't run for this row
    )
    regions = RegionsEvent(candidates=[high_score_no_rerank, high_rerank_low_score])

    ev = await inspect_regions(
        _q(),
        _plan(max_crops=2),
        regions,
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
    )
    # 0.55 × (2.0 × 0.95) = 1.045 vs 0.95 — high-rerank wins.
    assert ev.packets[0].bbox_norm == (0.05, 0.05, 0.40, 0.30)


async def test_rank_score_drops_low_rerank_below_unscored(tmp_path, monkeypatch):
    """A region scored relevance=0.05 by the reranker (basically irrelevant)
    falls behind even mediocre unscored regions."""
    inspect_calls: list = []
    text_calls: list = []
    _install_fake_tools(monkeypatch, inspect_calls=inspect_calls, text_calls=text_calls)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    low_rerank_high_score = RegionCandidate(
        region_id="low_rerank",
        page=1,
        bbox_norm=(0.10, 0.10, 0.40, 0.40),
        region_type="picture",
        score=0.95,
        relevance=0.05,  # reranker says it's irrelevant
    )
    decent_unscored = RegionCandidate(
        region_id="decent",
        page=1,
        bbox_norm=(0.55, 0.55, 0.90, 0.90),
        region_type="text",
        score=0.50,
        relevance=None,
    )
    regions = RegionsEvent(candidates=[low_rerank_high_score, decent_unscored])
    ev = await inspect_regions(
        _q(),
        _plan(max_crops=2),
        regions,
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
    )
    # 0.95 × (2.0 × 0.05) = 0.095 vs unscored 0.50 — decent_unscored wins.
    assert ev.packets[0].bbox_norm == (0.55, 0.55, 0.90, 0.90)


async def test_rank_score_primary_role_pulls_forward(tmp_path, monkeypatch):
    """needed_for='primary' applies a 1.3× boost; a primary-tagged region
    outranks an equivalent untagged one with the same relevance."""
    inspect_calls: list = []
    text_calls: list = []
    _install_fake_tools(monkeypatch, inspect_calls=inspect_calls, text_calls=text_calls)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    primary = RegionCandidate(
        region_id="primary",
        page=1,
        bbox_norm=(0.10, 0.10, 0.40, 0.40),
        region_type="text",
        score=0.50,
        relevance=0.50,
        needed_for="primary",
    )
    secondary = RegionCandidate(
        region_id="legend",
        page=1,
        bbox_norm=(0.55, 0.55, 0.90, 0.90),
        region_type="text",
        score=0.50,
        relevance=0.50,
        needed_for="legend_binding",
    )
    regions = RegionsEvent(candidates=[secondary, primary])
    ev = await inspect_regions(
        _q(),
        _plan(max_crops=2),
        regions,
        images_by_page={1: tmp_path / "p1.png"},
        pdf_path=pdf,
    )
    assert ev.packets[0].region_id if hasattr(ev.packets[0], "region_id") else True
    # Primary (0.50 × 1.0 × 1.3 = 0.65) > Secondary (0.50 × 1.0 = 0.50).
    assert ev.packets[0].bbox_norm == (0.10, 0.10, 0.40, 0.40)
