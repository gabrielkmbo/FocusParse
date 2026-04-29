"""Tests for `focusparse.eval.tile` (Phase 2 — parser-bench tiled protocols).

Covers:
  * `make_contact_sheet` lays out 2/4/8 images in the right grid
  * `make_contact_sheet` downscales when result exceeds max_dim
  * `prepare_tiled_images` returns the input unchanged when tiling
    isn't possible (no staged pages, single page + no PDF)
  * `prepare_tiled_images` composes a tile when staged pages alone meet
    the count
  * `prepare_tiled_images` renders noise pages from PDF when staged
    pages are insufficient
  * the tile path is content-addressed by example.id (no rerender on
    second call)
  * deterministic shuffle via example.id seed
  * graceful degradation: no PDF, fewer-than-N staged pages → returns
    staged pages unchanged
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from focusparse.eval.tile import TILE_SIZES, make_contact_sheet, prepare_tiled_images

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_solid_png(path: Path, *, color: tuple[int, int, int], size: tuple[int, int]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color=color).save(path, format="PNG")
    return path


def _write_pdf(path: Path, *, n_pages: int) -> Path:
    """Build a tiny PDF with `n_pages` numbered pages."""
    import fitz

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    for i in range(n_pages):
        page = doc.new_page(width=200, height=300)
        page.insert_text((50, 50), f"page {i + 1}", fontsize=14)
    doc.save(path)
    doc.close()
    return path


def _benchmark_example(
    *,
    example_id: str = "ex-tile",
    page_images: list[str] | None = None,
    supporting_pages: list[int] | None = None,
    source_pdf: str = "doc.pdf",
):
    """Build a minimal BenchmarkExample for tile tests."""
    from focusparse._parser_bench import (
        AnswerType,
        BBox,
        BenchmarkExample,
        DifficultyScores,
        Domain,
    )

    return BenchmarkExample(
        id=example_id,
        domain=Domain.DATASHEET,
        source_pdf=source_pdf,
        page_images=page_images or [f"images/{example_id}_page_0001_300dpi.png"],
        question="?",
        answer="x",
        answer_type=AnswerType.EXACT_MATCH,
        supporting_pages=supporting_pages or [1],
        supporting_bboxes=[BBox(page=1, x0=0, y0=0, x1=1, y1=1)],
        difficulty=DifficultyScores(visual=1, reasoning=1, localization=1),
        question_family="single_value_lookup",
    )


# ---------------------------------------------------------------------------
# make_contact_sheet
# ---------------------------------------------------------------------------


def test_make_contact_sheet_2up_lays_out_1x2(tmp_path):
    p1 = _write_solid_png(tmp_path / "p1.png", color=(255, 0, 0), size=(100, 200))
    p2 = _write_solid_png(tmp_path / "p2.png", color=(0, 255, 0), size=(100, 200))
    out_path = tmp_path / "tile.png"

    out, layout = make_contact_sheet([p1, p2], out_path, n_images=2)
    assert out.exists()

    # 2-up at cols=ceil(sqrt(2))=2, rows=1 → 200×200
    with Image.open(out) as img:
        assert img.size == (200, 200)
    # Layout has both filenames mapped.
    assert "p1.png" in layout
    assert "p2.png" in layout
    # Slot 0 at origin; slot 1 to the right.
    assert layout["p1.png"] == (0, 0)
    assert layout["p2.png"] == (100, 0)


def test_make_contact_sheet_4up_lays_out_2x2(tmp_path):
    paths = [
        _write_solid_png(tmp_path / f"p{i}.png", color=(i * 60, i * 60, i * 60), size=(80, 100))
        for i in range(4)
    ]
    out_path = tmp_path / "tile.png"
    out, layout = make_contact_sheet(paths, out_path, n_images=4)
    with Image.open(out) as img:
        # 4-up at 2×2 → 160×200
        assert img.size == (160, 200)
    # All 4 filenames placed.
    assert len(layout) == 4


def test_make_contact_sheet_8up_uses_4x2_layout(tmp_path):
    """parser-bench uses 4×2 for 8-up rather than 3×3 with one empty."""
    paths = [
        _write_solid_png(tmp_path / f"p{i}.png", color=(0, 0, 0), size=(50, 70)) for i in range(8)
    ]
    out_path = tmp_path / "tile.png"
    out, layout = make_contact_sheet(paths, out_path, n_images=8)
    with Image.open(out) as img:
        # 4 cols × 2 rows × (50×70) = 200×140
        assert img.size == (200, 140)
    assert len(layout) == 8


def test_make_contact_sheet_downscales_when_exceeding_max_dim(tmp_path):
    """A 4-up of 4000×4000 panes would be 8000×8000 — exceeds the 7680
    cap, so the sheet gets resized while preserving aspect."""
    # 4 panes at 4000×4000 → sheet would be 8000×8000.
    paths = [
        _write_solid_png(tmp_path / f"p{i}.png", color=(0, 0, 0), size=(4000, 4000))
        for i in range(4)
    ]
    out_path = tmp_path / "tile.png"
    out, layout = make_contact_sheet(paths, out_path, n_images=4, max_dim=7680)
    with Image.open(out) as img:
        # Longer side = 7680 after scaling 8000 → 7680 (factor 0.96).
        assert max(img.size) == 7680
    # Layout offsets get scaled too.
    for _, (x, y) in layout.items():
        assert x < 7680
        assert y < 7680


def test_make_contact_sheet_raises_on_empty_input(tmp_path):
    with pytest.raises(ValueError, match="No images"):
        make_contact_sheet([], tmp_path / "tile.png", n_images=0)


# ---------------------------------------------------------------------------
# prepare_tiled_images — staged-only path
# ---------------------------------------------------------------------------


def test_prepare_tiled_returns_empty_when_no_staged_pages(tmp_path, parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")
    example = _benchmark_example()
    # All staged paths missing on disk.
    out = prepare_tiled_images(
        example,
        n_tile=4,
        staged_pages=[tmp_path / "missing.png"],
        pdf_path=None,
        tile_cache_dir=tmp_path / "tiles",
    )
    assert out == []


def test_prepare_tiled_falls_back_when_no_pdf_for_noise(tmp_path, parser_bench_submodule_present):
    """Single staged page + no PDF + n_tile=4 → can't tile, return
    staged pages unchanged so the harness still has a list of paths."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    p1 = _write_solid_png(tmp_path / "p1.png", color=(255, 0, 0), size=(100, 100))
    example = _benchmark_example()
    out = prepare_tiled_images(
        example,
        n_tile=4,
        staged_pages=[p1],
        pdf_path=None,
        tile_cache_dir=tmp_path / "tiles",
    )
    # Single page is < 2 → can't compose; return staged pages unchanged.
    assert out == [p1]


def test_prepare_tiled_composes_when_staged_pages_meet_count(
    tmp_path, parser_bench_submodule_present
):
    """Two staged pages + n_tile=2 → no PDF needed; tile composed in place."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    p1 = _write_solid_png(tmp_path / "p1.png", color=(255, 0, 0), size=(100, 200))
    p2 = _write_solid_png(tmp_path / "p2.png", color=(0, 255, 0), size=(100, 200))
    example = _benchmark_example(page_images=["p1.png", "p2.png"])
    tile_dir = tmp_path / "tiles"

    out = prepare_tiled_images(
        example,
        n_tile=2,
        staged_pages=[p1, p2],
        pdf_path=None,
        tile_cache_dir=tile_dir,
    )
    assert len(out) == 1
    assert out[0].exists()
    # Tile lives under tile_cache_dir.
    assert out[0].parent == tile_dir


def test_prepare_tiled_renders_noise_from_pdf_when_short(tmp_path, parser_bench_submodule_present):
    """1 staged page + n_tile=4 + PDF available → renders 3 noise pages
    from the PDF and composes a 4-up tile."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    p1 = _write_solid_png(tmp_path / "p1.png", color=(255, 0, 0), size=(100, 100))
    pdf = _write_pdf(tmp_path / "doc.pdf", n_pages=10)
    example = _benchmark_example(supporting_pages=[3])

    out = prepare_tiled_images(
        example,
        n_tile=4,
        staged_pages=[p1],
        pdf_path=pdf,
        tile_cache_dir=tmp_path / "tiles",
    )
    # One tile output.
    assert len(out) == 1
    assert out[0].exists()
    # Noise pages cached separately under tiles/noise/.
    noise_dir = tmp_path / "tiles" / "noise"
    assert noise_dir.exists()
    rendered = list(noise_dir.glob("*.png"))
    assert len(rendered) >= 3
    # None of the noise pages should be page 3 (the gold supporting page).
    for n in rendered:
        # Filenames: doc_noise_page_NNNN_300dpi.png — extract NNNN.
        import re

        m = re.search(r"page_(\d+)", n.stem)
        if m:
            assert int(m.group(1)) != 3


def test_prepare_tiled_is_content_addressed(tmp_path, parser_bench_submodule_present):
    """Second call with same example.id + same n_tile hits the cached
    tile file (no recomposition)."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    p1 = _write_solid_png(tmp_path / "p1.png", color=(255, 0, 0), size=(100, 100))
    p2 = _write_solid_png(tmp_path / "p2.png", color=(0, 255, 0), size=(100, 100))
    example = _benchmark_example(example_id="ex-cache", page_images=["p1.png", "p2.png"])
    tile_dir = tmp_path / "tiles"

    out1 = prepare_tiled_images(
        example,
        n_tile=2,
        staged_pages=[p1, p2],
        pdf_path=None,
        tile_cache_dir=tile_dir,
    )
    mtime_before = out1[0].stat().st_mtime

    out2 = prepare_tiled_images(
        example,
        n_tile=2,
        staged_pages=[p1, p2],
        pdf_path=None,
        tile_cache_dir=tile_dir,
    )
    assert out2 == out1
    # File wasn't recreated.
    assert out2[0].stat().st_mtime == mtime_before


@pytest.mark.parametrize("protocol,n_tile", list(TILE_SIZES.items()))
def test_tile_sizes_table_exposes_supported_protocols(protocol, n_tile):
    """Sanity check on the protocol → n_tile mapping that the harness reads."""
    assert protocol.startswith("tiled_")
    assert n_tile in (2, 4, 8)


# ---------------------------------------------------------------------------
# Phase 3: agentic_multi_page protocol (b+c hybrid)
# ---------------------------------------------------------------------------


def test_sample_agentic_tile_size_is_deterministic():
    from focusparse.eval.tile import sample_agentic_tile_size

    assert sample_agentic_tile_size("ex-A") == sample_agentic_tile_size("ex-A")
    assert sample_agentic_tile_size("ex-B") == sample_agentic_tile_size("ex-B")
    for eid in ("a", "b", "c", "d", "e"):
        assert sample_agentic_tile_size(eid) in (2, 4, 8)


def test_sample_agentic_tile_size_distribution_is_middle_heavy():
    """Over many distinct ids, 4 should dominate (weight=0.5 vs 0.25/0.25)."""
    from focusparse.eval.tile import sample_agentic_tile_size

    counts = {2: 0, 4: 0, 8: 0}
    for i in range(2000):
        counts[sample_agentic_tile_size(f"ex-{i}")] += 1
    assert counts[4] > counts[2]
    assert counts[4] > counts[8]
    assert counts[4] > 1.5 * counts[2]
    assert counts[4] > 1.5 * counts[8]


def test_prepare_agentic_multi_page_composes_summary_when_enough_pages(
    tmp_path, parser_bench_submodule_present
):
    """≥ tile_size staged pages → composes a summary view PNG."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    from focusparse.eval.tile import prepare_agentic_multi_page, sample_agentic_tile_size

    pages = [
        _write_solid_png(tmp_path / f"p{i}.png", color=(i * 30, 0, 0), size=(100, 100))
        for i in range(8)
    ]
    example = _benchmark_example(
        example_id="ex-bundle-A",
        page_images=[f"p{i}.png" for i in range(8)],
    )
    cache_dir = tmp_path / "agentic_cache"

    bundle = prepare_agentic_multi_page(
        example,
        staged_pages=pages,
        pdf_path=None,
        cache_dir=cache_dir,
    )
    assert len(bundle.page_list) == 8
    assert bundle.summary_tile_size == sample_agentic_tile_size("ex-bundle-A")
    assert bundle.summary_view is not None
    assert bundle.summary_view.exists()


def test_prepare_agentic_multi_page_handles_zero_pages(tmp_path, parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    from focusparse.eval.tile import prepare_agentic_multi_page

    example = _benchmark_example(example_id="ex-empty")
    cache_dir = tmp_path / "agentic_cache"

    bundle = prepare_agentic_multi_page(
        example,
        staged_pages=[],
        pdf_path=None,
        cache_dir=cache_dir,
    )
    assert bundle.page_list == []
    assert bundle.summary_view is None
    # tile_size always set; the field is non-optional.
    assert bundle.summary_tile_size in (2, 4, 8)


def test_prepare_agentic_multi_page_is_content_addressed(tmp_path, parser_bench_submodule_present):
    """Re-call with the same example.id → same summary view file (no recompose)."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    from focusparse.eval.tile import prepare_agentic_multi_page

    pages = [
        _write_solid_png(tmp_path / f"p{i}.png", color=(0, i * 30, 0), size=(100, 100))
        for i in range(8)
    ]
    example = _benchmark_example(
        example_id="ex-cache",
        page_images=[f"p{i}.png" for i in range(8)],
    )
    cache_dir = tmp_path / "agentic_cache"

    b1 = prepare_agentic_multi_page(example, staged_pages=pages, pdf_path=None, cache_dir=cache_dir)
    assert b1.summary_view is not None
    mtime = b1.summary_view.stat().st_mtime

    b2 = prepare_agentic_multi_page(example, staged_pages=pages, pdf_path=None, cache_dir=cache_dir)
    assert b2.summary_view == b1.summary_view
    assert b2.summary_view.stat().st_mtime == mtime
    assert b2.summary_tile_size == b1.summary_tile_size
