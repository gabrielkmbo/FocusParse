"""Tests for `focusparse.pipeline.localizer.propose_regions`.

Monkeypatches `detect_layout` so no network + no real PNGs are required.
Covers the happy path, every fallback branch, bbox normalization math,
score blending, and the figure_class signal.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from focusparse.pipeline.events import (
    PageCandidate,
    PagesEvent,
    PlanEvent,
    QuestionEvent,
)
from focusparse.pipeline.localizer import propose_regions
from focusparse.tools.layout_detect import (
    DetectedBox,
    LayoutDetectionOutput,
    LayoutEndpointUnavailable,
    StubResponseError,
)


def _question() -> QuestionEvent:
    return QuestionEvent(
        example_id="ex-1",
        question="What is VCC max?",
        doc_id="datasheet-A",
        pages_available=10,
    )


def _plan() -> PlanEvent:
    return PlanEvent(
        question_family="single_value_lookup",
        evidence_types=["table"],
        budget_class="easy_local",
        routing_policy="layout_first",
        max_tool_calls=12,
        max_crops=8,
        max_vlm_calls=4,
    )


def _pages(*specs: tuple[int, float]) -> PagesEvent:
    return PagesEvent(
        candidates=[PageCandidate(page=p, score=s, reason_code="layout_prior") for p, s in specs]
    )


def _write_tiny_png(path: Path, *, width: int = 1000, height: int = 1500) -> Path:
    """Write a real but minimal PNG so the localizer can open it with PIL."""
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (width, height), color="white").save(path, format="PNG")
    return path


# ---------------------------------------------------------------------------
# Happy path + normalization
# ---------------------------------------------------------------------------


async def test_propose_regions_emits_one_candidate_per_detected_box(tmp_path, monkeypatch):
    png_path = _write_tiny_png(tmp_path / "p3.png", width=1000, height=2000)
    calls: list[dict] = []

    async def _fake_detect(png_bytes, *, page, image_width, image_height, **kwargs):
        calls.append(
            {
                "page": page,
                "image_width": image_width,
                "image_height": image_height,
                **kwargs,
            }
        )
        return LayoutDetectionOutput(
            page=page,
            width=image_width,
            height=image_height,
            boxes=[
                DetectedBox(label="text", bbox=(100.0, 200.0, 500.0, 1000.0), score=0.9),
                DetectedBox(
                    label="picture",
                    bbox=(0.0, 1200.0, 1000.0, 2000.0),
                    score=0.7,
                    figure_class="bar_chart",
                ),
            ],
        )

    monkeypatch.setattr("focusparse.pipeline.localizer.detect_layout", _fake_detect)

    regions = await propose_regions(
        _question(),
        _plan(),
        _pages((3, 0.8)),
        images_by_page={3: png_path},
    )

    assert len(regions.candidates) == 2
    r1, r2 = regions.candidates

    # Normalization: (100, 200, 500, 1000) / (1000, 2000) -> (0.1, 0.1, 0.5, 0.5)
    assert r1.bbox_norm == (0.1, 0.1, 0.5, 0.5)
    assert r1.region_type == "text"
    # Score is detector-only (decoupled from page score on 2026-04-27).
    assert r1.score == pytest.approx(0.9)
    assert "layout_detect" in r1.supporting_signals
    # Page-routing reason_code carried over for trace attribution.
    assert "page_routing=layout_prior" in r1.supporting_signals

    # Second box spans the full width but only the bottom half.
    assert r2.bbox_norm == (0.0, 0.6, 1.0, 1.0)
    assert r2.region_type == "picture"
    assert r2.score == pytest.approx(0.7)
    assert "layout_detect" in r2.supporting_signals
    assert "figure_class=bar_chart" in r2.supporting_signals
    assert "page_routing=layout_prior" in r2.supporting_signals

    # Dimensions get piped through from the on-disk PNG, not guessed.
    assert calls[0]["image_width"] == 1000
    assert calls[0]["image_height"] == 2000
    assert calls[0]["page"] == 3


async def test_propose_regions_clamps_bbox_to_unit_interval(tmp_path, monkeypatch):
    """Detector boxes occasionally overrun image bounds; clamp to [0,1]."""
    png_path = _write_tiny_png(tmp_path / "p1.png", width=100, height=100)

    async def _fake_detect(png_bytes, *, page, image_width, image_height, **kwargs):
        return LayoutDetectionOutput(
            page=page,
            width=image_width,
            height=image_height,
            boxes=[
                DetectedBox(label="text", bbox=(-10.0, -5.0, 120.0, 130.0), score=0.9),
            ],
        )

    monkeypatch.setattr("focusparse.pipeline.localizer.detect_layout", _fake_detect)

    regions = await propose_regions(
        _question(),
        _plan(),
        _pages((1, 1.0)),
        images_by_page={1: png_path},
    )
    assert regions.candidates[0].bbox_norm == (0.0, 0.0, 1.0, 1.0)


async def test_propose_regions_forwards_endpoint_and_cache_kwargs(tmp_path, monkeypatch):
    png_path = _write_tiny_png(tmp_path / "p1.png")
    captured: dict = {}

    async def _fake_detect(png_bytes, **kwargs):
        captured.update(kwargs)
        return LayoutDetectionOutput(
            page=kwargs["page"],
            width=kwargs["image_width"],
            height=kwargs["image_height"],
            boxes=[DetectedBox(label="text", bbox=(0.0, 0.0, 10.0, 10.0), score=0.9)],
        )

    monkeypatch.setattr("focusparse.pipeline.localizer.detect_layout", _fake_detect)
    cache_dir = tmp_path / "layout_cache"

    await propose_regions(
        _question(),
        _plan(),
        _pages((1, 1.0)),
        images_by_page={1: png_path},
        layout_endpoint_url="https://example.com/layout",
        hf_token="explicit-token",
        cache_dir=cache_dir,
        confidence_threshold=0.42,
    )

    assert captured["endpoint_url"] == "https://example.com/layout"
    assert captured["hf_token"] == "explicit-token"
    assert captured["cache_dir"] == cache_dir
    assert captured["confidence_threshold"] == 0.42


# ---------------------------------------------------------------------------
# Fallback branches
# ---------------------------------------------------------------------------


async def test_propose_regions_skeleton_on_endpoint_unavailable(tmp_path, monkeypatch):
    png_path = _write_tiny_png(tmp_path / "p1.png")

    async def _fake_detect(png_bytes, **kwargs):
        raise LayoutEndpointUnavailable("simulated outage")

    monkeypatch.setattr("focusparse.pipeline.localizer.detect_layout", _fake_detect)

    regions = await propose_regions(
        _question(),
        _plan(),
        _pages((1, 0.9)),
        images_by_page={1: png_path},
    )
    assert len(regions.candidates) == 1
    r = regions.candidates[0]
    assert r.bbox_norm == (0.0, 0.0, 1.0, 1.0)
    assert "skeleton_full_page" in r.supporting_signals
    assert "layout_endpoint_down" in r.supporting_signals
    # Skeleton retains the page's score (no detector to blend with).
    assert r.score == 0.9


async def test_propose_regions_skeleton_on_stub_response(tmp_path, monkeypatch):
    png_path = _write_tiny_png(tmp_path / "p1.png")

    async def _fake_detect(png_bytes, **kwargs):
        raise StubResponseError("got the full-page stub")

    monkeypatch.setattr("focusparse.pipeline.localizer.detect_layout", _fake_detect)

    regions = await propose_regions(
        _question(),
        _plan(),
        _pages((1, 0.5)),
        images_by_page={1: png_path},
    )
    assert len(regions.candidates) == 1
    assert "layout_endpoint_stub" in regions.candidates[0].supporting_signals


async def test_propose_regions_skeleton_when_no_boxes_above_threshold(tmp_path, monkeypatch):
    png_path = _write_tiny_png(tmp_path / "p1.png")

    async def _fake_detect(png_bytes, *, page, image_width, image_height, **kwargs):
        # Threshold filtering happens inside detect_layout; emulate it by
        # returning an empty boxes list.
        return LayoutDetectionOutput(page=page, width=image_width, height=image_height, boxes=[])

    monkeypatch.setattr("focusparse.pipeline.localizer.detect_layout", _fake_detect)

    regions = await propose_regions(
        _question(),
        _plan(),
        _pages((1, 0.5)),
        images_by_page={1: png_path},
    )
    assert len(regions.candidates) == 1
    assert "layout_no_boxes_above_threshold" in regions.candidates[0].supporting_signals


async def test_propose_regions_skeleton_when_image_missing(tmp_path, monkeypatch):
    # Dangling path: file never created.
    missing = tmp_path / "does-not-exist.png"

    async def _fake_detect(*args, **kwargs):
        raise AssertionError("detect_layout must not be called when file is missing")

    monkeypatch.setattr("focusparse.pipeline.localizer.detect_layout", _fake_detect)

    regions = await propose_regions(
        _question(),
        _plan(),
        _pages((1, 0.7)),
        images_by_page={1: missing},
    )
    assert len(regions.candidates) == 1
    assert "image_missing" in regions.candidates[0].supporting_signals


async def test_propose_regions_skeleton_when_page_not_in_images_map(monkeypatch):
    async def _fake_detect(*args, **kwargs):
        raise AssertionError("detect_layout must not be called with empty images map")

    monkeypatch.setattr("focusparse.pipeline.localizer.detect_layout", _fake_detect)

    regions = await propose_regions(
        _question(),
        _plan(),
        _pages((1, 0.7), (2, 0.3)),
        images_by_page={},  # intentionally empty
    )
    assert len(regions.candidates) == 2
    assert all("no_image_for_page" in r.supporting_signals for r in regions.candidates)


async def test_propose_regions_is_per_page_independent(tmp_path, monkeypatch):
    """One page succeeds, another fails — both get a candidate."""
    good_png = _write_tiny_png(tmp_path / "good.png", width=100, height=100)
    bad_png = _write_tiny_png(tmp_path / "bad.png", width=100, height=100)

    async def _fake_detect(png_bytes, *, page, image_width, image_height, **kwargs):
        if page == 2:
            raise LayoutEndpointUnavailable("half-down")
        return LayoutDetectionOutput(
            page=page,
            width=image_width,
            height=image_height,
            boxes=[DetectedBox(label="text", bbox=(0.0, 0.0, 50.0, 50.0), score=0.8)],
        )

    monkeypatch.setattr("focusparse.pipeline.localizer.detect_layout", _fake_detect)

    regions = await propose_regions(
        _question(),
        _plan(),
        _pages((1, 1.0), (2, 1.0)),
        images_by_page={1: good_png, 2: bad_png},
    )

    assert len(regions.candidates) == 2
    r1 = next(r for r in regions.candidates if r.page == 1)
    r2 = next(r for r in regions.candidates if r.page == 2)
    assert "layout_detect" in r1.supporting_signals
    assert "page_routing=layout_prior" in r1.supporting_signals
    assert "layout_endpoint_down" in r2.supporting_signals
    assert "page_routing=layout_prior" in r2.supporting_signals


async def test_propose_regions_legacy_shape_with_no_images_by_page(monkeypatch):
    """Old call sites that pass no images_by_page still get one region per page."""

    async def _fake_detect(*args, **kwargs):
        raise AssertionError("detect_layout must not be called without images")

    monkeypatch.setattr("focusparse.pipeline.localizer.detect_layout", _fake_detect)

    regions = await propose_regions(
        _question(),
        _plan(),
        _pages((5, 0.4), (6, 0.6)),
    )
    assert [r.page for r in regions.candidates] == [5, 6]
    assert all(r.bbox_norm == (0.0, 0.0, 1.0, 1.0) for r in regions.candidates)
    assert all("skeleton_full_page" in r.supporting_signals for r in regions.candidates)


# ---------------------------------------------------------------------------
# Decoupled scoring (regression guard for the 2026-04-27 page-score bug)
# ---------------------------------------------------------------------------


async def test_propose_regions_score_independent_of_page_score(tmp_path, monkeypatch):
    """Page score 0.0 (sqlite FTS5 single-doc match) used to zero every
    region. Now `region.score == det.score` regardless of `pc.score`.
    """
    png_path = _write_tiny_png(tmp_path / "p1.png", width=1000, height=1000)

    async def _fake_detect(png_bytes, *, page, image_width, image_height, **kwargs):
        return LayoutDetectionOutput(
            page=page,
            width=image_width,
            height=image_height,
            boxes=[
                DetectedBox(label="picture", bbox=(0.0, 0.0, 500.0, 500.0), score=0.85),
                DetectedBox(label="text", bbox=(500.0, 500.0, 1000.0, 1000.0), score=0.6),
            ],
        )

    monkeypatch.setattr("focusparse.pipeline.localizer.detect_layout", _fake_detect)

    # The smoke-bug scenario: route_pages emitted score=0.0 but reason=text_fts_match.
    pages_event = PagesEvent(
        candidates=[PageCandidate(page=1, score=0.0, reason_code="text_fts_match")]
    )

    regions = await propose_regions(
        _question(),
        _plan(),
        pages_event,
        images_by_page={1: png_path},
    )
    assert len(regions.candidates) == 2
    scores = sorted(r.score for r in regions.candidates)
    # Detector scores survive intact — no longer zeroed by pc.score=0.
    assert scores == pytest.approx([0.6, 0.85])
    # Routing signal still recorded for trace attribution.
    assert all("page_routing=text_fts_match" in r.supporting_signals for r in regions.candidates)


async def test_skeleton_region_records_page_routing_signal(tmp_path, monkeypatch):
    """The fallback path must also stamp the page-routing reason code so traces
    can distinguish a stub from a layout-down match."""
    png_path = _write_tiny_png(tmp_path / "p1.png")

    async def _fake_detect(png_bytes, **kwargs):
        raise LayoutEndpointUnavailable("simulated outage")

    monkeypatch.setattr("focusparse.pipeline.localizer.detect_layout", _fake_detect)

    pages_event = PagesEvent(
        candidates=[PageCandidate(page=1, score=0.0, reason_code="text_fts_no_matches")]
    )
    regions = await propose_regions(
        _question(),
        _plan(),
        pages_event,
        images_by_page={1: png_path},
    )
    r = regions.candidates[0]
    assert "skeleton_full_page" in r.supporting_signals
    assert "layout_endpoint_down" in r.supporting_signals
    assert "page_routing=text_fts_no_matches" in r.supporting_signals
