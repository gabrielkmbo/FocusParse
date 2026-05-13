"""PROPOSE_REGIONS stage — layout-driven region proposals with deterministic fallback.

Phase 2 sub-phase 2e replaces the skeleton full-page placeholder with a call
to the layout endpoint per candidate page. Detected boxes are translated into
`RegionCandidate`s with normalized bboxes. By default, any endpoint
failure (`LayoutEndpointUnavailable` or `StubResponseError`) degrades to the
old full-page skeleton region for *that page only*, so the workflow always has
something to feed the inspector. Research evals can pass
`allow_endpoint_fallback=False` to fail fast instead of mixing endpoint outage
behavior into headline numbers.

The localizer serializes its calls (one `await` per page) to respect the
endpoint's ≤ 2 req/s shared-usage budget. It does NOT enforce a global rate
limit across concurrent examples — that is the caller's concern.

Future sub-phases add OCR token anchors, question-family priors, and a
cheap-tier LLM rerank for ambiguous pages. For now, the contract is: if
layout_detect returns N boxes we emit N candidates, ranked by detector score.

Scoring contract (decoupled, 2026-04-27): `RegionCandidate.score` is the
detector confidence only, NOT a blend of page score × detector score.
The router and the localizer answer different questions ("which pages?"
vs "which boxes?") and mixing the two via multiplication zeroes every
region when the router returns 0.0 — which sqlite FTS5's BM25 does for
a single-document `text_fts_match`. The page-routing signal is preserved
in `RegionCandidate.supporting_signals` (`page_routing=<reason_code>`)
so the inspector / future rerank can re-introduce page weighting on a
per-question basis.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

from focusparse.pipeline.events import (
    PageCandidate,
    PagesEvent,
    PlanEvent,
    QuestionEvent,
    RegionCandidate,
    RegionsEvent,
)
from focusparse.tools.layout_detect import (
    LayoutEndpointUnavailable,
    StubResponseError,
    detect_layout,
)

logger = logging.getLogger(__name__)

_DEFAULT_CONFIDENCE_THRESHOLD = 0.3


async def propose_regions(
    question: QuestionEvent,
    plan: PlanEvent,
    pages: PagesEvent,
    *,
    images_by_page: dict[int, Path] | None = None,
    layout_endpoint_url: str | None = None,
    hf_token: str | None = None,
    cache_dir: Path | None = None,
    confidence_threshold: float = _DEFAULT_CONFIDENCE_THRESHOLD,
    allow_endpoint_fallback: bool = True,
    layout_max_retries: int | None = None,
    layout_timeout_s: float | None = None,
) -> RegionsEvent:
    """Propose candidate regions per page, with deterministic fallback.

    Args:
        question / plan / pages: upstream events.
        images_by_page: 1-indexed page number -> PNG path. When omitted (or a
            page is missing), the full-page skeleton region is emitted for
            that page so downstream stages never see an empty candidate set.
        layout_endpoint_url: override the default layout endpoint.
        hf_token: explicit token override. Defaults are handled by `detect_layout`.
        cache_dir: where `detect_layout` persists responses. If None, no cache.
        confidence_threshold: drop detector boxes below this score.
        allow_endpoint_fallback: when False, endpoint outage/stub errors are
            re-raised instead of converted to full-page skeleton regions.
        layout_max_retries / layout_timeout_s: optional transport overrides
            forwarded to `detect_layout`.

    Returns:
        A `RegionsEvent` with at least one candidate per page that was
        successfully processed (either real boxes, or a skeleton fallback).
    """
    del question, plan  # reserved for priors + LLM rerank in later sub-phases

    candidates: list[RegionCandidate] = []
    for pc in pages.candidates:
        image_path = (images_by_page or {}).get(pc.page)
        if image_path is None:
            candidates.append(_skeleton_region(pc, signal="no_image_for_page"))
            continue
        if not Path(image_path).exists():
            # Caller handed us a dangling path — don't fail the whole run,
            # and don't burn a network call we already know will be useless.
            candidates.append(_skeleton_region(pc, signal="image_missing"))
            continue

        try:
            page_regions = await _detect_for_page(
                pc,
                image_path=image_path,
                endpoint_url=layout_endpoint_url,
                hf_token=hf_token,
                cache_dir=cache_dir,
                confidence_threshold=confidence_threshold,
                layout_max_retries=layout_max_retries,
                layout_timeout_s=layout_timeout_s,
            )
        except LayoutEndpointUnavailable as exc:
            if not allow_endpoint_fallback:
                raise
            logger.warning(
                "layout endpoint unavailable on page=%d (%s); emitting skeleton region",
                pc.page,
                exc,
            )
            candidates.append(_skeleton_region(pc, signal="layout_endpoint_down"))
            continue
        except StubResponseError as exc:
            if not allow_endpoint_fallback:
                raise
            logger.warning(
                "layout endpoint returned stub on page=%d (%s); emitting skeleton region",
                pc.page,
                exc,
            )
            candidates.append(_skeleton_region(pc, signal="layout_endpoint_stub"))
            continue

        if not page_regions:
            # Endpoint returned no boxes above threshold — still give the
            # inspector a region to crop. Mark the signal so traces carry why.
            candidates.append(_skeleton_region(pc, signal="layout_no_boxes_above_threshold"))
            continue

        candidates.extend(page_regions)

    return RegionsEvent(candidates=candidates)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


async def _detect_for_page(
    pc: PageCandidate,
    *,
    image_path: Path,
    endpoint_url: str | None,
    hf_token: str | None,
    cache_dir: Path | None,
    confidence_threshold: float,
    layout_max_retries: int | None,
    layout_timeout_s: float | None,
) -> list[RegionCandidate]:
    """Call `detect_layout` on one page and translate the boxes to candidates."""
    png_bytes = Path(image_path).read_bytes()
    width, height = _png_dimensions(png_bytes)
    transport_kwargs: dict[str, float | int] = {}
    if layout_max_retries is not None:
        transport_kwargs["max_retries"] = layout_max_retries
    if layout_timeout_s is not None:
        transport_kwargs["timeout_s"] = layout_timeout_s

    out = await detect_layout(
        png_bytes,
        page=pc.page,
        image_width=width,
        image_height=height,
        endpoint_url=endpoint_url,
        hf_token=hf_token,
        cache_dir=cache_dir,
        confidence_threshold=confidence_threshold,
        **transport_kwargs,
    )

    regions: list[RegionCandidate] = []
    for idx, det in enumerate(out.boxes):
        x0, y0, x1, y1 = det.bbox
        bbox_norm = (
            _clamp_unit(x0 / width),
            _clamp_unit(y0 / height),
            _clamp_unit(x1 / width),
            _clamp_unit(y1 / height),
        )
        signals = ["layout_detect", f"page_routing={pc.reason_code}"]
        if det.figure_class:
            signals.append(f"figure_class={det.figure_class}")
        regions.append(
            RegionCandidate(
                region_id=f"r{idx}_p{pc.page}",
                page=pc.page,
                bbox_norm=bbox_norm,
                region_type=det.label or None,
                # Score is the detector confidence only — decoupled from
                # `pc.score`. The router's job is "which pages?"; the
                # localizer's job is "which boxes?". Mixing them via
                # multiplication zeroed every region whenever the router
                # returned BM25 0.0 for a single-doc text_fts_match (the
                # 2026-04-27 smoke bug). The page-routing signal is kept
                # in `supporting_signals` so traces still show it.
                score=float(det.score),
                supporting_signals=signals,
            )
        )
    return regions


def _skeleton_region(pc: PageCandidate, *, signal: str) -> RegionCandidate:
    """Full-page fallback region when layout detection is unusable.

    Score stays at `pc.score`: a skeleton has no detector confidence to
    score on, so the page-routing signal is the only thing left. The
    inspector's evidence-type boost compares everything on the same
    scale, so a low-pc.score skeleton naturally ranks below real
    detections — which is exactly what we want.
    """
    return RegionCandidate(
        region_id=f"r0_p{pc.page}",
        page=pc.page,
        bbox_norm=(0.0, 0.0, 1.0, 1.0),
        region_type=None,
        score=pc.score,
        supporting_signals=[
            "skeleton_full_page",
            signal,
            f"page_routing={pc.reason_code}",
        ],
    )


def _png_dimensions(png_bytes: bytes) -> tuple[int, int]:
    """Return (width, height) of a PNG without touching disk a second time."""
    # Deferred import: Pillow is in deps but keeping top-level imports lean.
    from PIL import Image

    with Image.open(io.BytesIO(png_bytes)) as img:
        return int(img.width), int(img.height)


def _clamp_unit(v: float) -> float:
    return max(0.0, min(1.0, float(v)))
