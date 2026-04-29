"""Contact-sheet tiling for the `tiled_{2,4,8}up` protocols.

parser-bench dropped `full_doc` in favor of three tiled protocols that
test "find the gold page among many." Each protocol packs N pages into
a single image: tiled_2up = 2 pages (1×2), tiled_4up = 4 (2×2),
tiled_8up = 8 (2×4 or similar). The gold supporting page sits among
N-1 noise pages from the same document.

This module mirrors parser-bench's `create_contact_sheet` for the
composition step (`make_contact_sheet`) and adds a noise-page pipeline
that renders from the source PDF via PyMuPDF when our HF staging only
has the gold pages cached. When no PDF is available, we degrade
gracefully to "tile what's staged" — fewer than N pages, but the
shape is still a tile, not a list.

Output paths are content-addressed so reruns hit the cache.
"""

from __future__ import annotations

import hashlib
import logging
import math
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from focusparse._parser_bench import BenchmarkExample


logger = logging.getLogger(__name__)

TILE_SIZES: dict[str, int] = {
    "tiled_2up": 2,
    "tiled_4up": 4,
    "tiled_8up": 8,
}

# Cap on either dimension before downscale. parser-bench uses 7680
# (Anthropic / Gemini share a ~7680 cap; OpenAI is more permissive).
# Keep the same default for parity.
_MAX_IMAGE_DIM = 7680
_NOISE_PAGE_DPI = 300  # match the staged gold pages' DPI

# Headline-table protocol (Phase 3 of the 2026-04-29 plan): each example
# exposes BOTH a tiled summary view (input b) AND the full page list
# (input c). Tile-size for the summary view is sampled per-example with
# weights below — middle-heavy because 4up is the most realistic "search
# a few pages" experience.
_AGENTIC_TILE_SIZES: tuple[int, ...] = (2, 4, 8)
_AGENTIC_TILE_WEIGHTS: tuple[float, ...] = (0.25, 0.5, 0.25)


@dataclass
class AgenticMultiPageInput:
    """Per-example input bundle for the `agentic_multi_page` protocol.

    Each method consumes what it needs:
      * Base VLM: only `summary_view`.
      * ReAct / Agent baseline: `summary_view` as initial input + tool
        access to read pages from `page_list` / `pdf_path`.
      * Our harness (FocusWorkflow): `page_list` + `pdf_path`. The
        summary view is recorded in trajectory metadata but the pipeline's
        router/localizer only operates on real pages.

    `summary_tile_size` is recorded per-example so the headline table
    can be split by tile-size if needed (appendix experiment).
    """

    summary_view: Path | None
    summary_tile_size: int  # 2, 4, or 8
    page_list: list[Path] = field(default_factory=list)
    pdf_path: Path | None = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def prepare_tiled_images(
    example: BenchmarkExample,
    n_tile: int,
    *,
    staged_pages: list[Path],
    pdf_path: Path | None,
    tile_cache_dir: Path,
    noise_cache_dir: Path | None = None,
) -> list[Path]:
    """Build a single N-up tile for one example.

    Args:
        example: the BenchmarkExample (used for source_pdf + supporting
            pages + the deterministic shuffle seed).
        n_tile: 2, 4, or 8.
        staged_pages: list of locally-resolved page-image paths that the
            HF staging dir already has (typically just the gold supporting
            pages — staging doesn't pull noise).
        pdf_path: optional source PDF. When present, missing noise pages
            are rendered from the PDF via PyMuPDF and cached.
        tile_cache_dir: where the composed tile PNG goes.
        noise_cache_dir: where noise PNGs go (defaults to a `noise/`
            subdir of `tile_cache_dir`).

    Returns:
        List with ONE path — the tile image. Falls back to the input
        `staged_pages` list when there are too few pages to tile.
    """
    if n_tile < 1:
        raise ValueError(f"n_tile must be ≥ 1; got {n_tile}")

    support_pages: list[Path] = [p for p in staged_pages if p.exists()]
    if not support_pages:
        return []

    noise_needed = max(0, n_tile - len(support_pages))
    noise_pages: list[Path] = []
    # No PDF available → degrade silently. The model gets a smaller tile,
    # which is still a valid input shape.
    if noise_needed > 0 and pdf_path is not None and pdf_path.exists():
        cache_dir = noise_cache_dir or (tile_cache_dir / "noise")
        noise_pages = _render_noise_pages(
            pdf_path,
            count=noise_needed,
            exclude_pages={int(p) for p in (example.supporting_pages or [])},
            cache_dir=cache_dir,
            seed_key=example.id,
        )

    tile_pages = support_pages + noise_pages
    if len(tile_pages) < 2:
        # Can't tile a single image. Hand back what we have unchanged so
        # downstream stages see a list of page paths.
        return support_pages

    # Deterministic shuffle so the gold page isn't always in slot 0.
    seed = int(hashlib.sha256(f"{example.id}:{n_tile}".encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    rng.shuffle(tile_pages)

    tile_cache_dir.mkdir(parents=True, exist_ok=True)
    out_path = tile_cache_dir / f"{_safe_id(example.id)}_tiled_{n_tile}up.png"
    if out_path.exists():
        return [out_path]

    try:
        make_contact_sheet([str(p) for p in tile_pages], out_path, n_images=n_tile)
        return [out_path]
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "tile composition failed for %s (%d-up): %s — falling back to staged_pages",
            example.id,
            n_tile,
            exc,
        )
        return support_pages


def sample_agentic_tile_size(example_id: str) -> int:
    """Deterministically sample a tile size in {2, 4, 8} for an example.

    Seed = first 8 hex chars of `sha256(example_id)`. Same id → same size
    across runs, so cache lookups stay stable. Weights are middle-heavy
    so 4-up dominates (the most realistic "scan 4 pages at a glance" case).
    """
    seed = int(hashlib.sha256(example_id.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    return rng.choices(_AGENTIC_TILE_SIZES, weights=_AGENTIC_TILE_WEIGHTS, k=1)[0]


def prepare_agentic_multi_page(
    example: BenchmarkExample,
    *,
    staged_pages: list[Path],
    pdf_path: Path | None,
    cache_dir: Path,
    noise_cache_dir: Path | None = None,
) -> AgenticMultiPageInput:
    """Build the per-example bundle for the `agentic_multi_page` protocol.

    Returns the summary view (a tiled composition at a per-example tile
    size in {2, 4, 8}) plus the full page list. Methods consume what
    they need:
      * Base VLM uses only `summary_view`.
      * Tool-using methods get the full bundle.

    The summary view is content-addressed by `<example_id>_summary_<n>up.png`
    so reruns hit the cache. When tiling fails (no pages or composition
    error), `summary_view` is None and the methods that need it fall back
    to the staged-pages path.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Resolve real, on-disk pages for the page list.
    page_list = [p for p in staged_pages if p.exists()]
    tile_size = sample_agentic_tile_size(example.id)

    # Compose the summary view by reusing prepare_tiled_images. When too
    # few pages exist to tile, summary_view is None — the caller
    # gracefully degrades.
    summary_paths = prepare_tiled_images(
        example,
        tile_size,
        staged_pages=page_list,
        pdf_path=pdf_path,
        tile_cache_dir=cache_dir,
        noise_cache_dir=noise_cache_dir,
    )
    # `prepare_tiled_images` returns either a single composed tile or a
    # fallback list of staged pages. We only treat it as a summary when it
    # composed (returns exactly 1 path that looks like a tile).
    summary_view: Path | None = None
    if len(summary_paths) == 1 and "_tiled_" in summary_paths[0].name:
        summary_view = summary_paths[0]

    return AgenticMultiPageInput(
        summary_view=summary_view,
        summary_tile_size=tile_size,
        page_list=page_list,
        pdf_path=pdf_path,
    )


def make_contact_sheet(
    image_paths: list[str | Path],
    output_path: str | Path,
    n_images: int | None = None,
    max_dim: int = _MAX_IMAGE_DIM,
) -> tuple[Path, dict[str, tuple[int, int]]]:
    """Compose `image_paths[:n_images]` into one contact sheet PNG.

    Layout: cols = ceil(sqrt(N)), rows = ceil(N / cols).
      * 2 → 1×2  (or 2×1 — see below)
      * 4 → 2×2
      * 8 → 3×3 (last cell empty)  — note: parser-bench uses 2×4 by
        always rounding up; we match that exactly via ceil(sqrt(N))
        which gives 3, then ceil(N/cols)=3 for N=8, but visually 2×4
        works better. We fix this with an explicit 8-up special case.
    """
    from PIL import Image, ImageFile

    ImageFile.LOAD_TRUNCATED_IMAGES = True

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    n = n_images or len(image_paths)
    images = [Image.open(p) for p in image_paths[:n]]
    if not images:
        raise ValueError("No images provided")

    max_w = max(img.width for img in images)
    max_h = max(img.height for img in images)

    # Layout selection. parser-bench's `cols = ceil(sqrt(N))` matches
    # well for 2 (cols=2, rows=1), 4 (2×2). For 8 we explicitly pick 4
    # cols (2 rows) since that's the more common page-array layout.
    if len(images) == 8:
        cols, rows = 4, 2
    else:
        cols = math.ceil(math.sqrt(len(images)))
        rows = math.ceil(len(images) / cols)

    sheet_w = cols * max_w
    sheet_h = rows * max_h
    sheet = Image.new("RGB", (sheet_w, sheet_h), color=(255, 255, 255))

    page_layout: dict[str, tuple[int, int]] = {}
    for idx, img in enumerate(images):
        r = idx // cols
        c = idx % cols
        x_off = c * max_w
        y_off = r * max_h
        sheet.paste(img, (x_off, y_off))
        page_layout[Path(image_paths[idx]).name] = (x_off, y_off)

    if max(sheet_w, sheet_h) > max_dim:
        scale = max_dim / max(sheet_w, sheet_h)
        new_w = int(round(sheet_w * scale))
        new_h = int(round(sheet_h * scale))
        sheet = sheet.resize((new_w, new_h), Image.LANCZOS)
        page_layout = {
            k: (int(round(x * scale)), int(round(y * scale))) for k, (x, y) in page_layout.items()
        }
        logger.info(
            "Downscaled %d-up sheet %dx%d -> %dx%d (cap %d)",
            len(images),
            sheet_w,
            sheet_h,
            new_w,
            new_h,
            max_dim,
        )

    sheet.save(str(output_path))
    for img in images:
        img.close()
    logger.info(
        "Created %d-up contact sheet (%dx%d) -> %s",
        len(images),
        sheet.width,
        sheet.height,
        output_path,
    )
    return output_path, page_layout


# ---------------------------------------------------------------------------
# Noise page rendering (PyMuPDF)
# ---------------------------------------------------------------------------


def _render_noise_pages(
    pdf_path: Path,
    *,
    count: int,
    exclude_pages: set[int],
    cache_dir: Path,
    seed_key: str,
) -> list[Path]:
    """Render `count` random noise pages from `pdf_path` (excluding
    `exclude_pages`) at 300 DPI to `cache_dir`.

    Deterministic per `seed_key` (the example id). Cached so reruns
    are free. Falls back to fewer pages when the PDF is too short.
    """
    if count <= 0:
        return []

    cache_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(int(hashlib.sha256(seed_key.encode()).hexdigest()[:8], 16))

    import fitz

    out_paths: list[Path] = []
    try:
        with fitz.open(pdf_path) as doc:
            available = [p for p in range(1, doc.page_count + 1) if p not in exclude_pages]
            rng.shuffle(available)
            chosen = available[:count]
            for page_num in chosen:
                out_path = cache_dir / f"{pdf_path.stem}_noise_page_{page_num:04d}_300dpi.png"
                if not out_path.exists():
                    try:
                        page = doc[page_num - 1]
                        zoom = _NOISE_PAGE_DPI / 72.0
                        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
                        pix.save(str(out_path))
                    except Exception as exc:  # pragma: no cover — defensive
                        logger.warning(
                            "noise page render failed for %s page=%d: %s",
                            pdf_path.name,
                            page_num,
                            exc,
                        )
                        continue
                out_paths.append(out_path)
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("PyMuPDF open failed for %s: %s", pdf_path, exc)
        return []

    return out_paths


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------


_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def _safe_id(example_id: str) -> str:
    safe = _UNSAFE_CHARS.sub("_", example_id)
    if len(safe) > 120 or not safe:
        return hashlib.sha1(example_id.encode("utf-8")).hexdigest()[:16]
    return safe
