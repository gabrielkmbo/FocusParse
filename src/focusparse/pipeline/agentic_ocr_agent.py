"""AgenticOCR-style faithful-lite comparator.

This is not the official AgenticOCR trained policy or model stack. It is a
small proxy row for the related-work experiment program, built around the
same identity as the paper method: query-conditioned on-demand zoom/OCR,
anti-lazy crop behavior, duplicate-crop avoidance, and explicit evidence
packaging.

The action vocabulary is intentionally tiny:

    image   -> inspect_region(mode="image")
    element -> inspect_region(mode="element")
    region  -> inspect_region(mode="region")

`get_text_layer` is used only as a cheap page-hint source. The final answer is
grounded in inspected crops, not a full-document parse.
"""

from __future__ import annotations

import json
import logging
import re
import tempfile
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from focusparse.models.base import ModelClient, ModelResponse
from focusparse.pipeline.workflow import WorkflowResult
from focusparse.tools.get_text_layer import (
    GetTextLayerInput,
    GetTextLayerOutput,
    get_text_layer,
)
from focusparse.tools.inspect_region import (
    InspectRegionInput,
    InspectRegionOutput,
    inspect_region,
)
from focusparse.traces.recorder import (
    EvidencePacketSummary,
    TrajectoryRecorder,
    TrajectoryStep,
)

if TYPE_CHECKING:
    from focusparse._parser_bench import BenchmarkExample
    from focusparse.eval.metrics import AggregateMetrics

logger = logging.getLogger(__name__)

ActionMode = Literal["image", "element", "region"]
InspectRegionFunc = Callable[..., Awaitable[InspectRegionOutput]]
GetTextLayerFunc = Callable[..., Awaitable[GetTextLayerOutput]]

METHOD_LABEL = "AgenticOCR-style faithful-lite proxy"
METHOD_DESCRIPTION = (
    "Faithful-lite proxy for AgenticOCR-style query-conditioned crop/OCR. "
    "Not the official trained AgenticOCR code or model."
)

_DEFAULT_MAX_ITERATIONS = 5
_DEFAULT_MAX_CROPS = 4
_DEFAULT_MAX_HINT_PAGES = 8
_LAZY_AREA_THRESHOLD = 0.60
_DUPLICATE_IOU_THRESHOLD = 0.70
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_PAGE_IN_FILENAME_RE = re.compile(r"_page_(\d+)")
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "what",
    "which",
    "with",
}

_SYSTEM_PROMPT = (
    "You are running an AgenticOCR-style faithful-lite document comparator. "
    "This is NOT the official trained AgenticOCR model. You must answer by "
    "choosing small query-conditioned crops and reading them with OCR/visual "
    "zoom. Do not parse the full document. Do not request full-page crops.\n\n"
    "Output strict JSON in exactly one of these shapes:\n"
    '  {"action": "image", "page": 1, "bbox_norm": [x0,y0,x1,y1], '
    '"rationale": "..."}\n'
    '  {"action": "element", "page": 1, "bbox_norm": [x0,y0,x1,y1], '
    '"rationale": "..."}\n'
    '  {"action": "region", "page": 1, "bbox_norm": [x0,y0,x1,y1], '
    '"rationale": "..."}\n'
    '  {"action": "final", "final_answer": "...", "citations": '
    '[{"page": 1, "bbox": [x0,y0,x1,y1], "evidence_ref": "agenticocr_pkt_000"}]}\n\n'
    "The action names map to inspect_region modes: image=crop only, "
    "element=crop+OCR, region=crop+sub-layout+OCR. Use element for known text, "
    "region for mixed chart/table/caption structures, and image for visual-only "
    "reading. Bboxes are normalized [0,1]. Keep bbox area below 0.60 and avoid "
    "repeating overlapping crops."
)


@dataclass
class _PageHint:
    page: int
    score: int
    text: str
    source: str


@dataclass
class _CropRecord:
    packet_id: str
    page: int
    bbox_norm: tuple[float, float, float, float]
    mode: ActionMode
    crop_ref: str
    ocr_text: str | None
    confidence: float
    area_ratio: float
    latency_ms: int = 0


@dataclass
class _ActionTurn:
    is_final: bool
    action: ActionMode | None = None
    page: int | None = None
    bbox_norm: tuple[float, float, float, float] | None = None
    rationale: str = ""
    final_answer: str | None = None
    citations: list[dict[str, Any]] | None = None
    error: str | None = None


class AgenticOCRStyleAgent:
    """Constrained AgenticOCR-style proxy over FocusParse's inspect primitive."""

    def __init__(
        self,
        *,
        backend_client: ModelClient,
        max_iterations: int = _DEFAULT_MAX_ITERATIONS,
        max_crops: int = _DEFAULT_MAX_CROPS,
        max_hint_pages: int = _DEFAULT_MAX_HINT_PAGES,
        lazy_area_threshold: float = _LAZY_AREA_THRESHOLD,
        duplicate_iou_threshold: float = _DUPLICATE_IOU_THRESHOLD,
        inspect_region_func: InspectRegionFunc = inspect_region,
        get_text_layer_func: GetTextLayerFunc = get_text_layer,
    ) -> None:
        self.backend_client = backend_client
        self.max_iterations = int(max_iterations)
        self.max_crops = int(max_crops)
        self.max_hint_pages = int(max_hint_pages)
        self.lazy_area_threshold = float(lazy_area_threshold)
        self.duplicate_iou_threshold = float(duplicate_iou_threshold)
        self._inspect_region = inspect_region_func
        self._get_text_layer = get_text_layer_func

    async def run(
        self,
        example: BenchmarkExample,
        images: list[Path],
        *,
        pdf_path: Path | None = None,
        crop_cache_dir: Path | None = None,
        text_layer_cache_dir: Path | None = None,
        layout_endpoint_url: str | None = None,
        hf_token: str | None = None,
        layout_cache_dir: Path | None = None,
    ) -> WorkflowResult:
        recorder = TrajectoryRecorder(example_id=example.id, question=example.question)
        recorder.set_plan(
            {
                "agent": "agentic_ocr",
                "method_label": METHOD_LABEL,
                "official_agentic_ocr": False,
                "action_vocabulary": ["image", "element", "region"],
                "max_iterations": self.max_iterations,
                "max_crops": self.max_crops,
                "lazy_area_threshold": self.lazy_area_threshold,
                "duplicate_iou_threshold": self.duplicate_iou_threshold,
            }
        )

        page_candidates = _candidate_pages(example, images)
        initial_images = _initial_policy_images(images)
        total_tokens_in = 0
        total_tokens_out = 0
        total_usd = 0.0
        total_latency_ms = 0
        step_index = 0

        if pdf_path is None:
            recorder.record(
                TrajectoryStep(
                    step_index=step_index,
                    stage="agentic_ocr_setup",
                    tier="comparator",
                    action="missing_pdf_path",
                    args={"reason": "inspect_region requires a source PDF"},
                    obs_summary="No source PDF was provided; cannot run crop/OCR proxy.",
                )
            )
            trace = recorder.finalize(answer="Unanswerable", citations=[])
            return WorkflowResult(
                answer="Unanswerable",
                citations=[],
                trace=trace,
                telemetry={
                    "tokens_in": 0,
                    "tokens_out": 0,
                    "usd": 0.0,
                    "latency_ms": 0,
                    "agentic_ocr": _telemetry_block(
                        crops=[],
                        lazy_count=0,
                        duplicate_count=0,
                        rejected_count=0,
                        missing_pdf_path=True,
                    ),
                },
            )

        page_hints, hint_step = await self._collect_page_hints(
            example=example,
            pdf_path=pdf_path,
            pages=page_candidates,
            cache_dir=text_layer_cache_dir,
        )
        if hint_step is not None:
            hint_step.step_index = step_index
            recorder.record(hint_step)
            step_index += 1

        crops: list[_CropRecord] = []
        notes: list[str] = []
        answer = ""
        citations: list[dict[str, Any]] = []
        lazy_count = 0
        duplicate_count = 0
        rejected_count = 0

        for iteration in range(self.max_iterations):
            prompt = _policy_prompt(
                example=example,
                pages=page_candidates,
                page_hints=page_hints,
                crops=crops,
                notes=notes,
                crop_budget_remaining=max(0, self.max_crops - len(crops)),
            )
            response = await self.backend_client.predict(
                prompt=prompt,
                images=initial_images if iteration == 0 else _crop_images(crops),
                system=_SYSTEM_PROMPT,
            )
            total_tokens_in += response.tokens_in or 0
            total_tokens_out += response.tokens_out or 0
            total_usd += response.usd or 0.0
            total_latency_ms += response.latency_ms or 0

            turn = _parse_action_turn(response.text)
            recorder.record(
                TrajectoryStep(
                    step_index=step_index,
                    stage="agentic_ocr_policy",
                    tier="comparator",
                    action="final_answer" if turn.is_final else "select_crop",
                    args={
                        "iteration": iteration,
                        "parsed_action": turn.action,
                        "parsed_page": turn.page,
                        "parsed_bbox": list(turn.bbox_norm) if turn.bbox_norm else None,
                        "parse_error": turn.error,
                    },
                    obs_summary=(response.text or "")[:240],
                    tokens_in=response.tokens_in,
                    tokens_out=response.tokens_out,
                    usd=response.usd,
                    latency_ms=response.latency_ms,
                )
            )
            step_index += 1

            if turn.is_final:
                if not crops:
                    notes.append("Rejected final answer before any crop/OCR evidence.")
                    rejected_count += 1
                    continue
                answer = turn.final_answer or ""
                citations = _normalize_final_citations(turn.citations or [], crops)
                break

            if turn.error or turn.action is None or turn.page is None or turn.bbox_norm is None:
                notes.append(f"Invalid action: {turn.error or 'missing action fields'}.")
                rejected_count += 1
                continue

            if len(crops) >= self.max_crops:
                notes.append("Crop budget exhausted; answer from the existing evidence.")
                rejected_count += 1
                continue

            area = _bbox_area(turn.bbox_norm)
            if turn.page not in page_candidates:
                rejected_count += 1
                notes.append(
                    f"Rejected page {turn.page}; choose one of the allowed pages {page_candidates}."
                )
                step_index = _record_rejected_crop(
                    recorder,
                    step_index,
                    turn,
                    reason="page_not_in_agentic_input",
                    area_ratio=area,
                    duplicate_of=None,
                )
                continue
            duplicate_of = _duplicate_of(
                turn.page, turn.bbox_norm, crops, self.duplicate_iou_threshold
            )
            if area > self.lazy_area_threshold:
                lazy_count += 1
                rejected_count += 1
                notes.append(
                    "Rejected near-full-page crop "
                    f"(page={turn.page}, area={area:.2f}); choose a smaller region."
                )
                step_index = _record_rejected_crop(
                    recorder,
                    step_index,
                    turn,
                    reason="lazy_full_page_crop",
                    area_ratio=area,
                    duplicate_of=None,
                )
                continue
            if duplicate_of is not None:
                duplicate_count += 1
                rejected_count += 1
                notes.append(
                    f"Rejected duplicate crop overlapping {duplicate_of}; choose a new region."
                )
                step_index = _record_rejected_crop(
                    recorder,
                    step_index,
                    turn,
                    reason="duplicate_overlapping_crop",
                    area_ratio=area,
                    duplicate_of=duplicate_of,
                )
                continue

            inspect_started = time.perf_counter()
            inp = InspectRegionInput(
                doc_path=str(pdf_path),
                page=turn.page,
                bbox_norm=list(turn.bbox_norm),
                mode=turn.action,
            )
            out = await self._inspect_region(
                inp,
                cache_dir=crop_cache_dir,
                layout_endpoint_url=layout_endpoint_url,
                hf_token=hf_token,
                layout_cache_dir=layout_cache_dir,
            )
            latency_ms = out.latency_ms or int((time.perf_counter() - inspect_started) * 1000)
            packet_id = f"agenticocr_pkt_{len(crops):03d}"
            crop = _CropRecord(
                packet_id=packet_id,
                page=turn.page,
                bbox_norm=turn.bbox_norm,
                mode=turn.action,
                crop_ref=out.crop_ref,
                ocr_text=out.ocr_text,
                confidence=float(out.confidence or 0.0),
                area_ratio=area,
                latency_ms=latency_ms,
            )
            crops.append(crop)
            recorder.add_artifact(
                artifact_id=packet_id,
                kind="crop",
                path=out.crop_ref,
                page=turn.page,
                bbox_norm=turn.bbox_norm,
                packet_id=packet_id,
                stage="agentic_ocr_inspect",
                step_index=step_index,
                label=f"inspect_region:{turn.action}",
                meta={"area_ratio": area, "ocr_confidence": out.confidence},
            )
            recorder.record(
                TrajectoryStep(
                    step_index=step_index,
                    stage="agentic_ocr_inspect",
                    tier="comparator",
                    action="tool_call",
                    tool="inspect_region",
                    args={
                        "mode": turn.action,
                        "page": turn.page,
                        "bbox_norm": list(turn.bbox_norm),
                        "packet_id": packet_id,
                        "area_ratio": area,
                        "rationale": turn.rationale,
                    },
                    obs_ref=out.crop_ref,
                    obs_summary=_crop_obs_summary(crop),
                    latency_ms=latency_ms,
                    confidence=out.confidence,
                )
            )
            step_index += 1
            notes.append(_crop_obs_summary(crop))

        if not answer and crops:
            (
                answer,
                citations,
                response,
            ) = await self._fallback_final_answer(example, crops)
            total_tokens_in += response.tokens_in or 0
            total_tokens_out += response.tokens_out or 0
            total_usd += response.usd or 0.0
            total_latency_ms += response.latency_ms or 0
            recorder.record(
                TrajectoryStep(
                    step_index=step_index,
                    stage="agentic_ocr_final",
                    tier="comparator",
                    action="final_answer",
                    args={"fallback": True},
                    obs_summary=(response.text or "")[:240],
                    tokens_in=response.tokens_in,
                    tokens_out=response.tokens_out,
                    usd=response.usd,
                    latency_ms=response.latency_ms,
                )
            )
            step_index += 1
        elif not answer:
            answer = "Unanswerable"
            citations = []

        citations = _normalize_final_citations(citations, crops)
        recorder.set_evidence_snapshot([_packet_summary(c) for c in crops])
        trace = recorder.finalize(answer=answer, citations=citations)
        telemetry = {
            "tokens_in": total_tokens_in,
            "tokens_out": total_tokens_out,
            "usd": total_usd,
            "latency_ms": total_latency_ms,
            "n_tool_calls": len(crops),
            "agentic_ocr": _telemetry_block(
                crops=crops,
                lazy_count=lazy_count,
                duplicate_count=duplicate_count,
                rejected_count=rejected_count,
                missing_pdf_path=False,
            ),
            "largest_crop_area_ratio": max((c.area_ratio for c in crops), default=0.0),
            "lazy_crop_count": lazy_count,
            "duplicate_crop_count": duplicate_count,
            "rejected_crop_count": rejected_count,
            "inspected_crop_count": len(crops),
        }
        return WorkflowResult(answer=answer, citations=citations, trace=trace, telemetry=telemetry)

    async def _collect_page_hints(
        self,
        *,
        example: BenchmarkExample,
        pdf_path: Path,
        pages: list[int],
        cache_dir: Path | None,
    ) -> tuple[list[_PageHint], TrajectoryStep | None]:
        tokens = _query_tokens(example.question)
        hints: list[_PageHint] = []
        for page in pages[: self.max_hint_pages]:
            try:
                out = await self._get_text_layer(
                    GetTextLayerInput(doc_path=str(pdf_path), page=page, bbox_norm=None),
                    cache_dir=cache_dir,
                )
            except Exception as exc:  # noqa: BLE001 - page hints are optional
                logger.info("AgenticOCR page hint failed for %s page %s: %s", example.id, page, exc)
                continue
            text = (out.text or "").strip()
            if not text:
                continue
            score = _overlap_score(tokens, text)
            hints.append(
                _PageHint(
                    page=page,
                    score=score,
                    text=_compact_text(text, limit=360),
                    source=out.source,
                )
            )
        hints.sort(key=lambda h: (h.score, -h.page), reverse=True)
        hints = hints[:5]
        if not hints:
            return [], None
        step = TrajectoryStep(
            step_index=0,
            stage="agentic_ocr_page_hints",
            tier="comparator",
            action="tool_call",
            tool="get_text_layer",
            args={
                "pages_scanned": pages[: self.max_hint_pages],
                "top_pages": [h.page for h in hints],
                "scores": {str(h.page): h.score for h in hints},
            },
            obs_summary="; ".join(f"p{h.page} score={h.score} {h.text[:90]!r}" for h in hints[:3]),
        )
        return hints, step

    async def _fallback_final_answer(
        self,
        example: BenchmarkExample,
        crops: list[_CropRecord],
    ) -> tuple[str, list[dict[str, Any]], ModelResponse]:
        prompt = (
            f"Question: {example.question}\n\n"
            "Answer using only these AgenticOCR-style inspected crops. Return JSON "
            'like {"action":"final","final_answer":"...","citations":[...]}.\n\n'
            f"{_evidence_block(crops)}"
        )
        response = await self.backend_client.predict(
            prompt=prompt,
            images=_crop_images(crops),
            system=_SYSTEM_PROMPT,
        )
        turn = _parse_action_turn(response.text)
        if turn.is_final:
            return turn.final_answer or "", turn.citations or [], response
        return response.text.strip() or "Unanswerable", [], response


async def run_agentic_ocr_eval(
    examples: Iterable[BenchmarkExample],
    *,
    backend_client: ModelClient,
    backend: str,
    model: str,
    protocol: str,
    output_dir: Path,
    images_root: Path,
    limit: int | None = None,
    resume: bool = True,
    pdfs_root: Path | None = None,
    minimal_artifacts: bool = False,
) -> dict[str, Any]:
    """Run the AgenticOCR-style faithful-lite proxy over a benchmark slice.

    Kept here instead of touching the shared harness so Worker 4's write
    footprint stays inside the requested comparator module plus CLI wiring.
    The returned dict intentionally mirrors `focusparse.eval.harness`.
    """
    from focusparse.eval.harness import (
        _agentic_summary_meta,
        _aggregate_stages,
        _env_snapshot,
        _error_record,
        _image_dims_by_page,
        _prepare_images,
        _resolve_pdf_path,
        _safe_id,
        _score_and_record,
        _should_abort_eval_on_error,
    )
    from focusparse.eval.metrics import aggregate, aggregate_by_domain

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    pred_dir = output_dir / "predictions" if not minimal_artifacts else None
    if pred_dir is not None:
        pred_dir.mkdir(parents=True, exist_ok=True)
    else:
        resume = False

    agent = AgenticOCRStyleAgent(backend_client=backend_client)
    available_tools = [
        "get_text_layer:page_hints",
        "inspect_region:image",
        "inspect_region:element",
        "inspect_region:region",
    ]
    per_example: list[dict[str, Any]] = []
    started_at = time.time()
    n = 0

    for example in examples:
        if limit is not None and n >= limit:
            break
        n += 1

        cache_path = pred_dir / f"{_safe_id(example.id)}.json" if pred_dir is not None else None
        record: dict[str, Any] | None = None
        if cache_path is not None and resume and cache_path.exists():
            try:
                record = json.loads(cache_path.read_text())
                record["cache_hit"] = True
            except (json.JSONDecodeError, OSError):
                record = None

        if record is None:
            scratch = (
                tempfile.TemporaryDirectory(prefix=f"focusparse-agenticocr-{_safe_id(example.id)}-")
                if minimal_artifacts
                else None
            )
            try:
                artifact_root = Path(scratch.name) if scratch is not None else output_dir
                tile_cache_dir = artifact_root / "tiles"
                crop_cache_dir = artifact_root / "crops"
                text_layer_cache_dir = artifact_root / "text_layer"
                layout_cache_dir = artifact_root / "layout"
                images = _prepare_images(
                    example,
                    protocol=protocol,
                    images_root=images_root,
                    pdfs_root=pdfs_root,
                    tile_cache_dir=tile_cache_dir,
                )
                agentic_meta: dict[str, object] | None = None
                if protocol == "agentic_multi_page":
                    agentic_meta = _agentic_summary_meta(
                        example,
                        images_root,
                        pdfs_root,
                        tile_cache_dir,
                    )
                pdf_path = _resolve_pdf_path(pdfs_root, example) if pdfs_root else None
                try:
                    result = await agent.run(
                        example,
                        images,
                        pdf_path=pdf_path,
                        crop_cache_dir=crop_cache_dir,
                        text_layer_cache_dir=text_layer_cache_dir,
                        layout_cache_dir=layout_cache_dir,
                    )
                    image_dims = _image_dims_by_page(example, images)
                    record = _score_and_record(
                        example,
                        result,
                        protocol=protocol,
                        image_dims_by_page=image_dims,
                        available_tools=available_tools,
                    )
                    record["method_label"] = METHOD_LABEL
                    record["official_agentic_ocr"] = False
                    record["agentic_ocr_meta"] = result.telemetry.get("agentic_ocr", {})
                    if agentic_meta is not None:
                        record["agentic_meta"] = agentic_meta
                    if cache_path is not None:
                        cache_path.write_text(json.dumps(record, default=str))
                except Exception as exc:
                    if _should_abort_eval_on_error(exc):
                        raise
                    logger.exception("Example %s failed: %s", example.id, exc)
                    record = _error_record(example, protocol=protocol, error=str(exc))
                    record["method_label"] = METHOD_LABEL
                    record["official_agentic_ocr"] = False
            finally:
                if scratch is not None:
                    scratch.cleanup()

        per_example.append(record)

    aggregated: AggregateMetrics = aggregate(per_example)
    aggregated_by_domain = aggregate_by_domain(per_example)
    stage_aggregate = _aggregate_stages(per_example)
    run_manifest: dict[str, Any] = {
        "agent": "agentic_ocr",
        "method_label": METHOD_LABEL,
        "method_description": METHOD_DESCRIPTION,
        "official_agentic_ocr": False,
        "action_vocabulary": ["image", "element", "region"],
        "available_tools": available_tools,
        "backend": backend,
        "model": model,
        "protocol": protocol,
        "n_examples": n,
        "limit": limit,
        "started_at": started_at,
        "ended_at": time.time(),
        "aggregate": aggregated.model_dump(),
        "aggregate_by_domain": {k: v.model_dump() for k, v in aggregated_by_domain.items()},
        "stage_aggregate": stage_aggregate.model_dump(),
        "artifact_policy": {
            "minimal_artifacts": minimal_artifacts,
            "write_prediction_cache": pred_dir is not None,
            "resume": resume,
            "intermediate_artifacts": (
                "per_example_scratch" if minimal_artifacts else "output_dir"
            ),
        },
        "env_snapshot": _env_snapshot(),
    }
    (output_dir / "run.json").write_text(json.dumps(run_manifest, default=str, indent=2))
    (output_dir / "per_example.jsonl").write_text(
        "\n".join(json.dumps(r, default=str) for r in per_example) + ("\n" if per_example else "")
    )

    return {
        "manifest": run_manifest,
        "aggregate": aggregated,
        "aggregate_by_domain": aggregated_by_domain,
        "stage_aggregate": stage_aggregate,
        "per_example": per_example,
        "output_dir": str(output_dir),
    }


def _policy_prompt(
    *,
    example: BenchmarkExample,
    pages: list[int],
    page_hints: list[_PageHint],
    crops: list[_CropRecord],
    notes: list[str],
    crop_budget_remaining: int,
) -> str:
    parts = [
        f"Question: {example.question}",
        f"Allowed source pages: {pages}",
        f"Crop budget remaining: {crop_budget_remaining}",
    ]
    if page_hints:
        parts.append("Top page hints from native text (navigation only, not final evidence):")
        for hint in page_hints:
            parts.append(f"- page {hint.page} score={hint.score} source={hint.source}: {hint.text}")
    if crops:
        parts.append("Inspected crop evidence:")
        parts.append(_evidence_block(crops))
    else:
        parts.append("No crop evidence yet. You must call image, element, or region before final.")
    if notes:
        parts.append("Runner notes:")
        parts.extend(f"- {note}" for note in notes[-5:])
    parts.append(
        "Choose the next smallest useful crop, or final if the inspected crop evidence "
        "is sufficient. Never request a bbox whose area exceeds 0.60."
    )
    return "\n\n".join(parts)


def _evidence_block(crops: list[_CropRecord]) -> str:
    lines: list[str] = []
    for crop in crops:
        ocr = _compact_text(crop.ocr_text or "", limit=280)
        lines.append(
            f"- {crop.packet_id}: page={crop.page} mode={crop.mode} "
            f"bbox={list(crop.bbox_norm)} area={crop.area_ratio:.3f} "
            f"crop_ref={crop.crop_ref} ocr={ocr!r}"
        )
    return "\n".join(lines)


def _parse_action_turn(text: str) -> _ActionTurn:
    if not text:
        return _ActionTurn(is_final=True, final_answer="")
    candidate = text.strip()
    fence = _JSON_FENCE_RE.search(candidate)
    if fence:
        candidate = fence.group(1)
    else:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = candidate[start : end + 1]
    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError:
        return _ActionTurn(is_final=True, final_answer=text.strip())
    if not isinstance(obj, dict):
        return _ActionTurn(is_final=True, final_answer=text.strip())

    action = str(obj.get("action") or "").strip().lower()
    if "final_answer" in obj or action in {"final", "answer"}:
        citations = obj.get("citations") or []
        if not isinstance(citations, list):
            citations = []
        return _ActionTurn(
            is_final=True,
            final_answer=str(obj.get("final_answer", "")),
            citations=[c for c in citations if isinstance(c, dict)],
        )
    if action not in {"image", "element", "region"}:
        return _ActionTurn(is_final=False, error=f"unknown action {action!r}")
    bbox, err = _coerce_bbox(obj.get("bbox_norm") or obj.get("bbox"))
    if err is not None:
        return _ActionTurn(is_final=False, action=action, error=err)  # type: ignore[arg-type]
    try:
        page = int(obj.get("page"))
    except (TypeError, ValueError):
        return _ActionTurn(is_final=False, action=action, error="missing page")  # type: ignore[arg-type]
    return _ActionTurn(
        is_final=False,
        action=action,  # type: ignore[arg-type]
        page=page,
        bbox_norm=bbox,
        rationale=str(obj.get("rationale") or ""),
    )


def _coerce_bbox(raw: Any) -> tuple[tuple[float, float, float, float] | None, str | None]:
    if not (isinstance(raw, list | tuple) and len(raw) == 4):
        return None, "bbox_norm must be a 4-number list"
    try:
        x0, y0, x1, y1 = (float(v) for v in raw)
    except (TypeError, ValueError):
        return None, "bbox_norm values must be numeric"
    x0 = min(1.0, max(0.0, x0))
    y0 = min(1.0, max(0.0, y0))
    x1 = min(1.0, max(0.0, x1))
    y1 = min(1.0, max(0.0, y1))
    if x1 <= x0 or y1 <= y0:
        return None, "bbox_norm must have positive area"
    return (x0, y0, x1, y1), None


def _candidate_pages(example: BenchmarkExample, images: list[Path]) -> list[int]:
    pages: list[int] = []
    for image in images:
        page = _page_number_from_filename(image.name)
        if page is not None:
            pages.append(page)
    if not pages:
        for idx, _ in enumerate(getattr(example, "page_images", []) or []):
            pages.append(idx + 1)
    return list(dict.fromkeys(pages or [1]))


def _page_number_from_filename(name: str) -> int | None:
    m = _PAGE_IN_FILENAME_RE.search(name)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _initial_policy_images(images: list[Path]) -> list[Path] | None:
    if not images:
        return None
    # agentic_multi_page prepends a summary view whose filename has no page
    # number. Let the policy inspect that overview, not every page image.
    first = images[0]
    if _page_number_from_filename(first.name) is None:
        return [first]
    return [first]


def _crop_images(crops: list[_CropRecord]) -> list[Path] | None:
    paths = [Path(c.crop_ref) for c in crops[-4:] if c.crop_ref]
    return paths or None


def _normalize_final_citations(
    raw_citations: list[dict[str, Any]],
    crops: list[_CropRecord],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for cit in raw_citations:
        bbox_raw = cit.get("bbox") or cit.get("bbox_norm")
        bbox, err = _coerce_bbox(bbox_raw)
        if err is not None or bbox is None:
            continue
        try:
            page = int(cit.get("page"))
        except (TypeError, ValueError):
            continue
        item = {"page": page, "bbox": list(bbox)}
        evidence_ref = cit.get("evidence_ref") or _nearest_crop_ref(page, bbox, crops)
        if evidence_ref:
            item["evidence_ref"] = evidence_ref
        out.append(item)
    if out:
        return out
    return [
        {
            "page": crop.page,
            "bbox": list(crop.bbox_norm),
            "evidence_ref": crop.packet_id,
        }
        for crop in crops
    ]


def _nearest_crop_ref(
    page: int,
    bbox: tuple[float, float, float, float],
    crops: list[_CropRecord],
) -> str | None:
    best_ref: str | None = None
    best_iou = 0.0
    for crop in crops:
        if crop.page != page:
            continue
        iou = _bbox_iou(bbox, crop.bbox_norm)
        if iou > best_iou:
            best_iou = iou
            best_ref = crop.packet_id
    return best_ref if best_iou > 0.05 else None


def _packet_summary(crop: _CropRecord) -> EvidencePacketSummary:
    return EvidencePacketSummary(
        packet_id=crop.packet_id,
        page=crop.page,
        bbox_norm=crop.bbox_norm,
        local_crop_ref=crop.crop_ref,
        ocr_snippet=_compact_text(crop.ocr_text or "", limit=500) or None,
        confidence=crop.confidence,
        provenance_tool=f"inspect_region:{crop.mode}",
    )


def _record_rejected_crop(
    recorder: TrajectoryRecorder,
    step_index: int,
    turn: _ActionTurn,
    *,
    reason: str,
    area_ratio: float,
    duplicate_of: str | None,
) -> int:
    recorder.record(
        TrajectoryStep(
            step_index=step_index,
            stage="agentic_ocr_inspect",
            tier="comparator",
            action="crop_rejected",
            args={
                "reason": reason,
                "tool": "inspect_region",
                "mode": turn.action,
                "page": turn.page,
                "bbox_norm": list(turn.bbox_norm) if turn.bbox_norm else None,
                "area_ratio": area_ratio,
                "duplicate_of": duplicate_of,
            },
            obs_summary=f"Rejected crop: {reason}",
        )
    )
    return step_index + 1


def _telemetry_block(
    *,
    crops: list[_CropRecord],
    lazy_count: int,
    duplicate_count: int,
    rejected_count: int,
    missing_pdf_path: bool,
) -> dict[str, Any]:
    crop_pairs = max(1, len(crops))
    return {
        "method_label": METHOD_LABEL,
        "official_agentic_ocr": False,
        "action_vocabulary": ["image", "element", "region"],
        "missing_pdf_path": missing_pdf_path,
        "inspected_crop_count": len(crops),
        "lazy_crop_count": lazy_count,
        "duplicate_crop_count": duplicate_count,
        "rejected_crop_count": rejected_count,
        "largest_crop_area_ratio": max((c.area_ratio for c in crops), default=0.0),
        "near_full_page_crop_rate": lazy_count / crop_pairs,
        "duplicate_crop_rate": duplicate_count / crop_pairs,
        "crop_area_ratios": [c.area_ratio for c in crops],
        "evidence_refs": [c.packet_id for c in crops],
    }


def _crop_obs_summary(crop: _CropRecord) -> str:
    ocr = _compact_text(crop.ocr_text or "", limit=180)
    parts = [
        f"{crop.packet_id} page={crop.page}",
        f"mode={crop.mode}",
        f"bbox={list(crop.bbox_norm)}",
        f"area={crop.area_ratio:.3f}",
        f"crop_ref={crop.crop_ref}",
    ]
    if ocr:
        parts.append(f"ocr={ocr!r}")
    return ", ".join(parts)


def _query_tokens(question: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall(question.lower()) if t not in _STOPWORDS and len(t) > 2}


def _overlap_score(query_tokens: set[str], text: str) -> int:
    if not query_tokens:
        return 0
    text_tokens = set(_TOKEN_RE.findall(text.lower()))
    return len(query_tokens & text_tokens)


def _compact_text(text: str, *, limit: int) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _bbox_area(bbox: tuple[float, float, float, float]) -> float:
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])


def _intersection_area(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    x0 = max(a[0], b[0])
    y0 = max(a[1], b[1])
    x1 = min(a[2], b[2])
    y1 = min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    return (x1 - x0) * (y1 - y0)


def _bbox_iou(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    inter = _intersection_area(a, b)
    union = _bbox_area(a) + _bbox_area(b) - inter
    return inter / union if union > 0 else 0.0


def _duplicate_of(
    page: int,
    bbox: tuple[float, float, float, float],
    crops: list[_CropRecord],
    threshold: float,
) -> str | None:
    for crop in crops:
        if crop.page != page:
            continue
        if _bbox_iou(bbox, crop.bbox_norm) > threshold:
            return crop.packet_id
    return None
