"""DocLens-style comparator agent.

This is a faithful DocLens-style proxy for the related-work experiment program.
Official DocLens code is not available in this repo, so this comparator mirrors
the method shape rather than claiming to be the original implementation:

1. page navigation by repeated page sampling and union,
2. element localization over layout boxes, native text, and crops,
3. bounded answer sampling from localized evidence,
4. lightweight adjudication across answer samples.

It intentionally stays a comparator, not a productized FocusParse workflow.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from focusparse.models.base import ModelClient, ModelResponse
from focusparse.pipeline.workflow import WorkflowResult
from focusparse.tools import GET_TEXT_LAYER_SPEC, INSPECT_REGION_SPEC, LAYOUT_DETECT_SPEC
from focusparse.traces.recorder import (
    EvidencePacketSummary,
    TrajectoryRecorder,
    TrajectoryStep,
)

if TYPE_CHECKING:
    from focusparse._parser_bench import BenchmarkExample

logger = logging.getLogger(__name__)

_DEFAULT_NAVIGATION_ROUNDS = 2
_DEFAULT_PAGES_PER_ROUND = 3
_DEFAULT_MAX_ELEMENTS = 5
_DEFAULT_ANSWER_SAMPLES = 2
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_PAGE_RE = re.compile(r"_page_(\d+)")

_NAVIGATION_SYSTEM = (
    "You are the page navigator in a faithful DocLens-style document QA proxy. "
    "Given a question plus page screenshots/page list, independently sample the "
    "pages most likely to contain the supporting evidence. Return STRICT JSON: "
    '{"pages": [1, 2], "rationale": "..."}'
)

_LOCALIZER_SYSTEM = (
    "You are the element localizer in a faithful DocLens-style document QA proxy. "
    "Given candidate layout/text observations, select the smallest elements that "
    "should be cropped/read before answering. Return STRICT JSON: "
    '{"elements": [{"ref": "cand_000", "reason": "..."}]}'
)

_ANSWER_SYSTEM = (
    "You are the answer sampler in a faithful DocLens-style document QA proxy. "
    "Answer only from the localized evidence. Return STRICT JSON: "
    '{"answer": "...", "evidence_refs": ["ev_000"], '
    '"citations": [{"page": 1, "bbox": [0, 0, 1, 1]}]}'
)

_ADJUDICATOR_SYSTEM = (
    "You are the adjudicator in a faithful DocLens-style document QA proxy. "
    "Choose the best answer sample using the localized evidence. Prefer answers "
    "with explicit supporting citations. Return STRICT JSON: "
    '{"selected": 0, "answer": "...", "evidence_refs": ["ev_000"], '
    '"citations": [{"page": 1, "bbox": [0, 0, 1, 1]}], "rationale": "..."}'
)


@dataclass(frozen=True)
class _PageEntry:
    page: int
    path: Path
    is_summary: bool = False


@dataclass
class _CandidateElement:
    ref: str
    page: int
    bbox: tuple[float, float, float, float]
    label: str
    score: float = 1.0
    text_snippet: str | None = None
    source: str = "layout"
    page_image: Path | None = None
    crop_ref: str | None = None
    ocr_text: str | None = None
    localizer_reason: str | None = None

    def citation(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "bbox": [float(v) for v in self.bbox],
            "evidence_ref": self.ref,
            "source": "doclens",
        }

    def evidence_summary(self) -> EvidencePacketSummary:
        return EvidencePacketSummary(
            packet_id=self.ref,
            page=self.page,
            bbox_norm=self.bbox,
            region_type=self.label,
            local_crop_ref=self.crop_ref,
            text_layer_snippet=self.text_snippet,
            ocr_snippet=self.ocr_text,
            confidence=float(self.score),
            provenance_tool="doclens_element_localizer",
        )


@dataclass
class _AnswerSample:
    answer: str
    citations: list[dict[str, Any]]
    evidence_refs: list[str]
    raw_text: str = ""


@dataclass
class _Usage:
    tokens_in: int = 0
    tokens_out: int = 0
    usd: float = 0.0
    latency_ms: int = 0

    def add_response(self, response: ModelResponse) -> None:
        self.tokens_in += int(response.tokens_in or 0)
        self.tokens_out += int(response.tokens_out or 0)
        self.usd += float(response.usd or 0.0)
        self.latency_ms += int(response.latency_ms or 0)


class DocLensAgent:
    """Bounded DocLens-style comparator.

    The public contract matches the other comparator agents: call `run()` with a
    benchmark example plus prepared page images, receive a `WorkflowResult`.
    """

    def __init__(
        self,
        *,
        backend_client: ModelClient,
        max_navigation_rounds: int = _DEFAULT_NAVIGATION_ROUNDS,
        pages_per_round: int = _DEFAULT_PAGES_PER_ROUND,
        max_elements: int = _DEFAULT_MAX_ELEMENTS,
        answer_samples: int = _DEFAULT_ANSWER_SAMPLES,
        layout_confidence_threshold: float = 0.3,
    ) -> None:
        if max_navigation_rounds < 1:
            raise ValueError("max_navigation_rounds must be >= 1")
        if pages_per_round < 1:
            raise ValueError("pages_per_round must be >= 1")
        if max_elements < 1:
            raise ValueError("max_elements must be >= 1")
        if answer_samples < 1:
            raise ValueError("answer_samples must be >= 1")
        self.backend_client = backend_client
        self.max_navigation_rounds = int(max_navigation_rounds)
        self.pages_per_round = int(pages_per_round)
        self.max_elements = int(max_elements)
        self.answer_samples = int(answer_samples)
        self.layout_confidence_threshold = float(layout_confidence_threshold)

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
                "agent": "doclens",
                "implementation_label": "faithful_doclens_style_proxy",
                "max_navigation_rounds": self.max_navigation_rounds,
                "pages_per_round": self.pages_per_round,
                "max_elements": self.max_elements,
                "answer_samples": self.answer_samples,
                "n_images": len(images),
            }
        )

        usage = _Usage()
        page_entries = _page_entries(images)
        diagnostics: dict[str, Any] = {
            "implementation_label": "faithful_doclens_style_proxy",
            "page_navigation": {},
            "element_localization": {},
            "answer_sampling": {},
            "adjudication": {},
        }

        step_index = 0
        selected_pages, nav_diag, step_index = await self._navigate_pages(
            example,
            page_entries,
            images,
            recorder=recorder,
            usage=usage,
            step_index=step_index,
        )
        diagnostics["page_navigation"] = nav_diag

        elements, loc_diag, step_index = await self._localize_elements(
            example,
            selected_pages,
            page_entries,
            pdf_path=pdf_path,
            crop_cache_dir=crop_cache_dir,
            text_layer_cache_dir=text_layer_cache_dir,
            layout_endpoint_url=layout_endpoint_url,
            hf_token=hf_token,
            layout_cache_dir=layout_cache_dir,
            recorder=recorder,
            usage=usage,
            step_index=step_index,
        )
        diagnostics["element_localization"] = loc_diag

        samples, sample_diag, step_index = await self._sample_answers(
            example,
            elements,
            selected_pages=selected_pages,
            page_entries=page_entries,
            recorder=recorder,
            usage=usage,
            step_index=step_index,
        )
        diagnostics["answer_sampling"] = sample_diag

        final, adj_diag, step_index = await self._adjudicate(
            example,
            samples,
            elements,
            recorder=recorder,
            usage=usage,
            step_index=step_index,
        )
        diagnostics["adjudication"] = adj_diag
        _ = step_index

        recorder.set_evidence_snapshot([e.evidence_summary() for e in elements])
        trace = recorder.finalize(answer=final.answer, citations=final.citations)
        telemetry = {
            "tokens_in": usage.tokens_in,
            "tokens_out": usage.tokens_out,
            "usd": usage.usd,
            "latency_ms": usage.latency_ms,
            "n_tool_calls": _count_tool_calls(trace.steps),
            "available_tools": [
                LAYOUT_DETECT_SPEC.name,
                GET_TEXT_LAYER_SPEC.name,
                INSPECT_REGION_SPEC.name,
            ],
            "doclens": diagnostics,
            "stage_diagnostics": {
                "page_navigation": diagnostics["page_navigation"],
                "element_localization": diagnostics["element_localization"],
                "answer_sampling": diagnostics["answer_sampling"],
                "adjudication": diagnostics["adjudication"],
            },
            "loop_terminated": "accepted" if final.answer else "abstained",
            "retries_used": 0,
        }
        return WorkflowResult(
            answer=final.answer,
            citations=final.citations,
            trace=trace,
            telemetry=telemetry,
        )

    async def _navigate_pages(
        self,
        example: BenchmarkExample,
        page_entries: list[_PageEntry],
        images: list[Path],
        *,
        recorder: TrajectoryRecorder,
        usage: _Usage,
        step_index: int,
    ) -> tuple[list[int], dict[str, Any], int]:
        valid_pages = [p.page for p in page_entries if not p.is_summary]
        if not valid_pages:
            valid_pages = [1]

        union: list[int] = []
        round_candidates: list[list[int]] = []
        nav_images = _navigation_images(images, page_entries)
        for round_idx in range(self.max_navigation_rounds):
            prompt = _navigation_prompt(
                example,
                page_entries,
                round_index=round_idx,
                selected_so_far=union,
                pages_per_round=self.pages_per_round,
            )
            response = await self.backend_client.predict(
                prompt=prompt,
                images=nav_images,
                system=_NAVIGATION_SYSTEM,
                max_tokens=700,
            )
            usage.add_response(response)
            pages = _parse_pages_response(
                response.text,
                valid_pages=valid_pages,
                max_pages=self.pages_per_round,
            )
            if not pages:
                pages = _fallback_pages(valid_pages, self.pages_per_round, offset=round_idx)
            for page in pages:
                if page not in union:
                    union.append(page)
            round_candidates.append(pages)
            recorder.record(
                TrajectoryStep(
                    step_index=step_index,
                    stage="route_pages",
                    tier="comparator",
                    action="page_navigation_sample",
                    tool=None,
                    args={
                        "round": round_idx + 1,
                        "candidates": pages,
                        "union_so_far": list(union),
                    },
                    obs_summary=_shorten(response.text, 220),
                    tokens_in=response.tokens_in,
                    tokens_out=response.tokens_out,
                    usd=response.usd,
                    latency_ms=response.latency_ms,
                )
            )
            step_index += 1

        selected = union[: max(1, self.pages_per_round * self.max_navigation_rounds)]
        return (
            selected,
            {
                "rounds": self.max_navigation_rounds,
                "pages_per_round": self.pages_per_round,
                "round_candidates": round_candidates,
                "selected_pages": selected,
                "valid_pages": valid_pages,
            },
            step_index,
        )

    async def _localize_elements(
        self,
        example: BenchmarkExample,
        selected_pages: list[int],
        page_entries: list[_PageEntry],
        *,
        pdf_path: Path | None,
        crop_cache_dir: Path | None,
        text_layer_cache_dir: Path | None,
        layout_endpoint_url: str | None,
        hf_token: str | None,
        layout_cache_dir: Path | None,
        recorder: TrajectoryRecorder,
        usage: _Usage,
        step_index: int,
    ) -> tuple[list[_CandidateElement], dict[str, Any], int]:
        by_page = {p.page: p for p in page_entries if not p.is_summary}
        candidates: list[_CandidateElement] = []
        text_by_page: dict[int, str] = {}
        tool_errors: list[dict[str, Any]] = []
        used_tools: set[str] = set()

        for page in selected_pages:
            entry = by_page.get(page)
            if entry is None:
                continue

            layout_elements, err, step_index = await self._layout_candidates_for_page(
                page,
                entry,
                recorder=recorder,
                step_index=step_index,
                layout_endpoint_url=layout_endpoint_url,
                hf_token=hf_token,
                layout_cache_dir=layout_cache_dir,
            )
            if err is not None:
                tool_errors.append(err)
            if layout_elements:
                used_tools.add(LAYOUT_DETECT_SPEC.name)
                candidates.extend(layout_elements)

            text, err, step_index = await self._text_for_page(
                page,
                pdf_path=pdf_path,
                recorder=recorder,
                step_index=step_index,
                text_layer_cache_dir=text_layer_cache_dir,
            )
            if err is not None:
                tool_errors.append(err)
            if text:
                used_tools.add(GET_TEXT_LAYER_SPEC.name)
                text_by_page[page] = text
                if not layout_elements:
                    candidates.append(
                        _CandidateElement(
                            ref=f"cand_{len(candidates):03d}",
                            page=page,
                            bbox=(0.0, 0.0, 1.0, 1.0),
                            label="text_layer_page",
                            text_snippet=_shorten(text, 400),
                            source="text_layer_fallback",
                            page_image=entry.path,
                        )
                    )

            if not layout_elements and not text:
                candidates.append(
                    _CandidateElement(
                        ref=f"cand_{len(candidates):03d}",
                        page=page,
                        bbox=(0.0, 0.0, 1.0, 1.0),
                        label="page",
                        source="page_fallback",
                        page_image=entry.path,
                    )
                )

        candidates = _dedupe_candidates(_rank_candidates(candidates))
        for idx, cand in enumerate(candidates):
            cand.ref = f"cand_{idx:03d}"
            if cand.text_snippet is None and cand.page in text_by_page:
                cand.text_snippet = _shorten(text_by_page[cand.page], 300)

        selected_refs, selector_diag, step_index = await self._select_candidate_elements(
            example,
            candidates,
            recorder=recorder,
            usage=usage,
            step_index=step_index,
        )
        selected = _select_by_refs(candidates, selected_refs, self.max_elements)

        inspected: list[_CandidateElement] = []
        for idx, cand in enumerate(selected):
            cand.ref = f"ev_{idx:03d}"
            updated, err, step_index = await self._inspect_candidate(
                cand,
                pdf_path=pdf_path,
                crop_cache_dir=crop_cache_dir,
                recorder=recorder,
                step_index=step_index,
                layout_endpoint_url=layout_endpoint_url,
                hf_token=hf_token,
                layout_cache_dir=layout_cache_dir,
            )
            if err is not None:
                tool_errors.append(err)
            if updated.crop_ref or updated.ocr_text is not None:
                used_tools.add(INSPECT_REGION_SPEC.name)
            inspected.append(updated)

        return (
            inspected,
            {
                "selected_pages": selected_pages,
                "candidate_count": len(candidates),
                "selected_count": len(inspected),
                "selected_refs": [e.ref for e in inspected],
                "used_tools": sorted(used_tools),
                "tool_errors": tool_errors[:8],
                "selector": selector_diag,
            },
            step_index,
        )

    async def _layout_candidates_for_page(
        self,
        page: int,
        entry: _PageEntry,
        *,
        recorder: TrajectoryRecorder,
        step_index: int,
        layout_endpoint_url: str | None,
        hf_token: str | None,
        layout_cache_dir: Path | None,
    ) -> tuple[list[_CandidateElement], dict[str, Any] | None, int]:
        if not entry.path.exists():
            return (
                [],
                {"tool": LAYOUT_DETECT_SPEC.name, "page": page, "error": "image_missing"},
                step_index,
            )
        try:
            inp = LAYOUT_DETECT_SPEC.input_model(
                image_path=str(entry.path),
                page=page,
                confidence_threshold=self.layout_confidence_threshold,
            )
            out = await LAYOUT_DETECT_SPEC.runner(
                inp,
                layout_endpoint_url=layout_endpoint_url,
                hf_token=hf_token,
                layout_cache_dir=layout_cache_dir,
            )
            regions = out.get("regions") or []
            width = int(out.get("image_width") or 0)
            height = int(out.get("image_height") or 0)
            candidates: list[_CandidateElement] = []
            for region in regions:
                bbox = _normalize_bbox(region.get("bbox"), width=width, height=height)
                if bbox is None:
                    continue
                candidates.append(
                    _CandidateElement(
                        ref="",
                        page=page,
                        bbox=bbox,
                        label=str(region.get("label") or "region"),
                        score=float(region.get("score") or 0.0),
                        source="layout_detect",
                        page_image=entry.path,
                    )
                )
            recorder.record(
                TrajectoryStep(
                    step_index=step_index,
                    stage="localize",
                    tier="comparator",
                    action="tool_call",
                    tool=LAYOUT_DETECT_SPEC.name,
                    args={"page": page, "n_regions": len(candidates)},
                    obs_summary=f"layout regions={len(candidates)}",
                )
            )
            return candidates, None, step_index + 1
        except Exception as exc:  # noqa: BLE001 - comparator fallback path
            logger.info("DocLens layout_detect failed on page %s: %s", page, exc)
            recorder.record(
                TrajectoryStep(
                    step_index=step_index,
                    stage="localize",
                    tier="comparator",
                    action="tool_error",
                    tool=LAYOUT_DETECT_SPEC.name,
                    args={"page": page, "error": type(exc).__name__},
                    obs_summary=str(exc)[:220],
                )
            )
            return (
                [],
                {"tool": LAYOUT_DETECT_SPEC.name, "page": page, "error": type(exc).__name__},
                step_index + 1,
            )

    async def _text_for_page(
        self,
        page: int,
        *,
        pdf_path: Path | None,
        recorder: TrajectoryRecorder,
        step_index: int,
        text_layer_cache_dir: Path | None,
    ) -> tuple[str | None, dict[str, Any] | None, int]:
        if pdf_path is None:
            return (
                None,
                {"tool": GET_TEXT_LAYER_SPEC.name, "page": page, "error": "pdf_missing"},
                step_index,
            )
        try:
            inp = GET_TEXT_LAYER_SPEC.input_model(doc_path=str(pdf_path), page=page, bbox_norm=None)
            out = await GET_TEXT_LAYER_SPEC.runner(inp, text_layer_cache_dir=text_layer_cache_dir)
            text = str(out.get("text") or "")
            source = str(out.get("source") or "")
            recorder.record(
                TrajectoryStep(
                    step_index=step_index,
                    stage="localize",
                    tier="comparator",
                    action="tool_call",
                    tool=GET_TEXT_LAYER_SPEC.name,
                    args={"page": page, "source": source, "n_chars": len(text)},
                    obs_summary=_shorten(text, 220),
                )
            )
            return text if text.strip() else None, None, step_index + 1
        except Exception as exc:  # noqa: BLE001 - comparator fallback path
            logger.info("DocLens get_text_layer failed on page %s: %s", page, exc)
            recorder.record(
                TrajectoryStep(
                    step_index=step_index,
                    stage="localize",
                    tier="comparator",
                    action="tool_error",
                    tool=GET_TEXT_LAYER_SPEC.name,
                    args={"page": page, "error": type(exc).__name__},
                    obs_summary=str(exc)[:220],
                )
            )
            return (
                None,
                {"tool": GET_TEXT_LAYER_SPEC.name, "page": page, "error": type(exc).__name__},
                step_index + 1,
            )

    async def _select_candidate_elements(
        self,
        example: BenchmarkExample,
        candidates: list[_CandidateElement],
        *,
        recorder: TrajectoryRecorder,
        usage: _Usage,
        step_index: int,
    ) -> tuple[list[str], dict[str, Any], int]:
        if not candidates:
            return [], {"method": "empty_candidates"}, step_index
        prompt = _localizer_prompt(example, candidates, max_elements=self.max_elements)
        response = await self.backend_client.predict(
            prompt=prompt,
            images=None,
            system=_LOCALIZER_SYSTEM,
            max_tokens=900,
        )
        usage.add_response(response)
        selected_refs = _parse_element_refs(response.text, candidates)
        if not selected_refs:
            selected_refs = [c.ref for c in candidates[: self.max_elements]]
        recorder.record(
            TrajectoryStep(
                step_index=step_index,
                stage="localize",
                tier="comparator",
                action="element_selection",
                tool=None,
                args={"selected_refs": selected_refs, "candidate_count": len(candidates)},
                obs_summary=_shorten(response.text, 220),
                tokens_in=response.tokens_in,
                tokens_out=response.tokens_out,
                usd=response.usd,
                latency_ms=response.latency_ms,
            )
        )
        return (
            selected_refs,
            {"method": "llm_selector", "selected_refs": selected_refs},
            step_index + 1,
        )

    async def _inspect_candidate(
        self,
        candidate: _CandidateElement,
        *,
        pdf_path: Path | None,
        crop_cache_dir: Path | None,
        recorder: TrajectoryRecorder,
        step_index: int,
        layout_endpoint_url: str | None,
        hf_token: str | None,
        layout_cache_dir: Path | None,
    ) -> tuple[_CandidateElement, dict[str, Any] | None, int]:
        if pdf_path is None:
            return (
                candidate,
                {"tool": INSPECT_REGION_SPEC.name, "page": candidate.page, "error": "pdf_missing"},
                step_index,
            )
        try:
            mode = "image" if candidate.label in {"chart", "picture"} else "element"
            inp = INSPECT_REGION_SPEC.input_model(
                doc_path=str(pdf_path),
                page=candidate.page,
                bbox_norm=[float(v) for v in candidate.bbox],
                mode=mode,
            )
            out = await INSPECT_REGION_SPEC.runner(
                inp,
                cache_dir=crop_cache_dir,
                layout_endpoint_url=layout_endpoint_url,
                hf_token=hf_token,
                layout_cache_dir=layout_cache_dir,
            )
            candidate.crop_ref = str(out.get("crop_ref") or "") or None
            candidate.ocr_text = out.get("ocr_text")
            recorder.record(
                TrajectoryStep(
                    step_index=step_index,
                    stage="localize",
                    tier="comparator",
                    action="tool_call",
                    tool=INSPECT_REGION_SPEC.name,
                    args={
                        "evidence_ref": candidate.ref,
                        "page": candidate.page,
                        "bbox": [float(v) for v in candidate.bbox],
                        "mode": mode,
                    },
                    obs_ref=candidate.crop_ref,
                    obs_summary=_shorten(candidate.ocr_text or candidate.crop_ref or "", 220),
                    latency_ms=int(out.get("latency_ms") or 0),
                )
            )
            return candidate, None, step_index + 1
        except (ValidationError, Exception) as exc:  # noqa: BLE001 - comparator fallback path
            logger.info("DocLens inspect_region failed on %s: %s", candidate.ref, exc)
            recorder.record(
                TrajectoryStep(
                    step_index=step_index,
                    stage="localize",
                    tier="comparator",
                    action="tool_error",
                    tool=INSPECT_REGION_SPEC.name,
                    args={
                        "evidence_ref": candidate.ref,
                        "page": candidate.page,
                        "error": type(exc).__name__,
                    },
                    obs_summary=str(exc)[:220],
                )
            )
            return (
                candidate,
                {
                    "tool": INSPECT_REGION_SPEC.name,
                    "page": candidate.page,
                    "error": type(exc).__name__,
                },
                step_index + 1,
            )

    async def _sample_answers(
        self,
        example: BenchmarkExample,
        elements: list[_CandidateElement],
        *,
        selected_pages: list[int],
        page_entries: list[_PageEntry],
        recorder: TrajectoryRecorder,
        usage: _Usage,
        step_index: int,
    ) -> tuple[list[_AnswerSample], dict[str, Any], int]:
        if not elements:
            fallback = _AnswerSample(answer="Unanswerable", citations=[], evidence_refs=[])
            return [fallback], {"sample_count": 0, "method": "no_evidence"}, step_index

        evidence_by_ref = {e.ref: e for e in elements}
        images = _answer_images(elements, selected_pages, page_entries)
        samples: list[_AnswerSample] = []
        for sample_idx in range(self.answer_samples):
            prompt = _answer_prompt(
                example,
                elements,
                sample_index=sample_idx,
                sample_count=self.answer_samples,
            )
            response = await self.backend_client.predict(
                prompt=prompt,
                images=images,
                system=_ANSWER_SYSTEM,
                max_tokens=900,
            )
            usage.add_response(response)
            sample = _parse_answer_sample(response.text, evidence_by_ref)
            sample.raw_text = response.text
            if not sample.citations:
                sample.citations = _citations_for_refs(sample.evidence_refs, evidence_by_ref)
            if not sample.evidence_refs and sample.citations:
                sample.evidence_refs = _refs_for_citations(sample.citations, evidence_by_ref)
            samples.append(sample)
            recorder.record(
                TrajectoryStep(
                    step_index=step_index,
                    stage="answer_sampling",
                    tier="comparator",
                    action="answer_sample",
                    tool=None,
                    args={
                        "sample_index": sample_idx,
                        "answer": sample.answer,
                        "evidence_refs": sample.evidence_refs,
                    },
                    obs_summary=_shorten(response.text, 220),
                    tokens_in=response.tokens_in,
                    tokens_out=response.tokens_out,
                    usd=response.usd,
                    latency_ms=response.latency_ms,
                )
            )
            step_index += 1

        return (
            samples,
            {
                "sample_count": len(samples),
                "answers": [s.answer for s in samples],
                "evidence_refs_by_sample": [s.evidence_refs for s in samples],
                "image_count": len(images or []),
            },
            step_index,
        )

    async def _adjudicate(
        self,
        example: BenchmarkExample,
        samples: list[_AnswerSample],
        elements: list[_CandidateElement],
        *,
        recorder: TrajectoryRecorder,
        usage: _Usage,
        step_index: int,
    ) -> tuple[_AnswerSample, dict[str, Any], int]:
        if not samples:
            final = _AnswerSample(answer="Unanswerable", citations=[], evidence_refs=[])
            return final, {"method": "empty_samples"}, step_index
        evidence_by_ref = {e.ref: e for e in elements}
        majority_idx = _majority_sample_index(samples)
        if majority_idx is not None:
            final = samples[majority_idx]
            if not final.citations:
                final.citations = _citations_for_refs(final.evidence_refs, evidence_by_ref)
            recorder.record(
                TrajectoryStep(
                    step_index=step_index,
                    stage="adjudication",
                    tier="comparator",
                    action="majority_vote",
                    args={
                        "selected_sample": majority_idx,
                        "answer": final.answer,
                        "sample_count": len(samples),
                    },
                    obs_summary=f"majority answer={final.answer}",
                )
            )
            return (
                final,
                {
                    "method": "majority_vote",
                    "selected_sample": majority_idx,
                    "disagreement": False,
                },
                step_index + 1,
            )

        prompt = _adjudication_prompt(example, samples, elements)
        response = await self.backend_client.predict(
            prompt=prompt,
            images=None,
            system=_ADJUDICATOR_SYSTEM,
            max_tokens=700,
        )
        usage.add_response(response)
        selected_idx, parsed = _parse_adjudication(response.text, samples, evidence_by_ref)
        final = parsed or samples[selected_idx]
        if not final.citations:
            final.citations = _citations_for_refs(final.evidence_refs, evidence_by_ref)
        recorder.record(
            TrajectoryStep(
                step_index=step_index,
                stage="adjudication",
                tier="comparator",
                action="llm_adjudication",
                args={
                    "selected_sample": selected_idx,
                    "answer": final.answer,
                    "sample_count": len(samples),
                },
                obs_summary=_shorten(response.text, 220),
                tokens_in=response.tokens_in,
                tokens_out=response.tokens_out,
                usd=response.usd,
                latency_ms=response.latency_ms,
            )
        )
        return (
            final,
            {
                "method": "llm_adjudicator",
                "selected_sample": selected_idx,
                "disagreement": True,
            },
            step_index + 1,
        )


def _page_entries(images: list[Path]) -> list[_PageEntry]:
    entries: list[_PageEntry] = []
    positional_page = 1
    for image in images:
        match = _PAGE_RE.search(image.name)
        if match:
            entries.append(_PageEntry(page=int(match.group(1)), path=image, is_summary=False))
            continue
        # In agentic_multi_page, the first non-page-named PNG is the summary
        # contact sheet. Keep it available for navigation but do not localize it.
        if not entries:
            entries.append(_PageEntry(page=0, path=image, is_summary=True))
            continue
        entries.append(_PageEntry(page=positional_page, path=image, is_summary=False))
        positional_page += 1
    return entries


def _navigation_images(images: list[Path], entries: list[_PageEntry]) -> list[Path] | None:
    summary = [e.path for e in entries if e.is_summary]
    if summary:
        return summary[:1]
    return images[:8] or None


def _navigation_prompt(
    example: BenchmarkExample,
    entries: list[_PageEntry],
    *,
    round_index: int,
    selected_so_far: list[int],
    pages_per_round: int,
) -> str:
    lines = [
        f"Question: {example.question}",
        f"Navigation sample: {round_index + 1}",
        f"Return at most {pages_per_round} pages.",
    ]
    domain = getattr(example, "domain", None)
    if domain is not None:
        lines.append(f"Domain: {str(domain).split('.')[-1].lower()}")
    if selected_so_far:
        lines.append(f"Pages already sampled by prior rounds: {selected_so_far}")
    lines.append("Available page inputs:")
    for entry in entries:
        if entry.is_summary:
            lines.append(f"- summary screenshot: {entry.path}")
        else:
            lines.append(f"- page {entry.page}: {entry.path}")
    return "\n".join(lines)


def _localizer_prompt(
    example: BenchmarkExample,
    candidates: list[_CandidateElement],
    *,
    max_elements: int,
) -> str:
    lines = [
        f"Question: {example.question}",
        f"Select up to {max_elements} candidate elements. Use refs exactly.",
        "Candidates:",
    ]
    for cand in candidates[:24]:
        text = f" text={cand.text_snippet!r}" if cand.text_snippet else ""
        lines.append(
            "- "
            f"{cand.ref}: page={cand.page} label={cand.label} "
            f"bbox={[round(v, 4) for v in cand.bbox]} score={cand.score:.2f}{text}"
        )
    return "\n".join(lines)


def _answer_prompt(
    example: BenchmarkExample,
    elements: list[_CandidateElement],
    *,
    sample_index: int,
    sample_count: int,
) -> str:
    lines = [
        f"Question: {example.question}",
        f"Answer sample {sample_index + 1} of {sample_count}.",
        "Use only the localized evidence below. Cite evidence_refs when possible.",
        "Localized evidence:",
    ]
    for element in elements:
        bits = [
            f"{element.ref}: page={element.page}",
            f"label={element.label}",
            f"bbox={[round(v, 4) for v in element.bbox]}",
        ]
        if element.crop_ref:
            bits.append(f"crop={element.crop_ref}")
        if element.text_snippet:
            bits.append(f"text={element.text_snippet!r}")
        if element.ocr_text:
            bits.append(f"ocr={_shorten(element.ocr_text, 220)!r}")
        lines.append("- " + " ".join(bits))
    return "\n".join(lines)


def _adjudication_prompt(
    example: BenchmarkExample,
    samples: list[_AnswerSample],
    elements: list[_CandidateElement],
) -> str:
    lines = [
        f"Question: {example.question}",
        "Localized evidence refs:",
    ]
    for element in elements:
        snippet = element.ocr_text or element.text_snippet or ""
        lines.append(
            f"- {element.ref}: page={element.page} bbox={[round(v, 4) for v in element.bbox]} "
            f"text={_shorten(snippet, 180)!r}"
        )
    lines.append("Answer samples:")
    for idx, sample in enumerate(samples):
        lines.append(
            f"- sample {idx}: answer={sample.answer!r} "
            f"evidence_refs={sample.evidence_refs} citations={sample.citations}"
        )
    return "\n".join(lines)


def _parse_pages_response(text: str, *, valid_pages: list[int], max_pages: int) -> list[int]:
    obj = _extract_json_obj(text)
    raw_pages = obj.get("pages") if isinstance(obj, dict) else None
    out: list[int] = []
    if isinstance(raw_pages, list):
        for raw in raw_pages:
            try:
                page = int(raw)
            except (TypeError, ValueError):
                continue
            if page in valid_pages and page not in out:
                out.append(page)
            if len(out) >= max_pages:
                break
    return out


def _parse_element_refs(text: str, candidates: list[_CandidateElement]) -> list[str]:
    obj = _extract_json_obj(text)
    valid = {c.ref for c in candidates}
    raw_elements = obj.get("elements") if isinstance(obj, dict) else None
    refs: list[str] = []
    if isinstance(raw_elements, list):
        for item in raw_elements:
            ref = item.get("ref") if isinstance(item, dict) else item
            if isinstance(ref, str) and ref in valid and ref not in refs:
                refs.append(ref)
    return refs


def _parse_answer_sample(text: str, evidence_by_ref: dict[str, _CandidateElement]) -> _AnswerSample:
    obj = _extract_json_obj(text)
    if not isinstance(obj, dict):
        return _AnswerSample(answer=text.strip(), citations=[], evidence_refs=[], raw_text=text)
    answer = obj.get("answer", obj.get("final_answer", ""))
    refs = _coerce_ref_list(
        obj.get("evidence_refs")
        or obj.get("citation_refs")
        or obj.get("citations_refs")
        or obj.get("refs")
    )
    citations = _coerce_citations(obj.get("citations"), evidence_by_ref)
    if refs and not citations:
        citations = _citations_for_refs(refs, evidence_by_ref)
    return _AnswerSample(
        answer=str(answer),
        citations=citations,
        evidence_refs=refs,
        raw_text=text,
    )


def _parse_adjudication(
    text: str,
    samples: list[_AnswerSample],
    evidence_by_ref: dict[str, _CandidateElement],
) -> tuple[int, _AnswerSample | None]:
    obj = _extract_json_obj(text)
    if not isinstance(obj, dict):
        return 0, None
    try:
        selected = int(obj.get("selected", obj.get("selected_sample", 0)))
    except (TypeError, ValueError):
        selected = 0
    selected = min(max(selected, 0), len(samples) - 1)
    if "answer" not in obj and "final_answer" not in obj:
        return selected, None
    refs = _coerce_ref_list(obj.get("evidence_refs") or obj.get("citation_refs"))
    citations = _coerce_citations(obj.get("citations"), evidence_by_ref)
    if refs and not citations:
        citations = _citations_for_refs(refs, evidence_by_ref)
    return (
        selected,
        _AnswerSample(
            answer=str(obj.get("answer", obj.get("final_answer", ""))),
            citations=citations,
            evidence_refs=refs,
            raw_text=text,
        ),
    )


def _extract_json_obj(text: str) -> dict[str, Any]:
    if not text:
        return {}
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
        return {}
    return obj if isinstance(obj, dict) else {}


def _coerce_ref_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and item not in out:
            out.append(item)
    return out


def _coerce_citations(
    raw: Any,
    evidence_by_ref: dict[str, _CandidateElement],
) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, str):
            element = evidence_by_ref.get(item)
            if element is not None:
                out.append(element.citation())
            continue
        if not isinstance(item, dict):
            continue
        ref = item.get("evidence_ref") or item.get("ref")
        if isinstance(ref, str) and ref in evidence_by_ref and "bbox" not in item:
            out.append(evidence_by_ref[ref].citation())
            continue
        bbox = item.get("bbox")
        try:
            page = int(item.get("page"))
            if not (isinstance(bbox, list | tuple) and len(bbox) == 4):
                continue
            cite = {
                "page": page,
                "bbox": [float(v) for v in bbox],
                "source": "doclens",
            }
            if isinstance(ref, str):
                cite["evidence_ref"] = ref
            out.append(cite)
        except (TypeError, ValueError):
            continue
    return out


def _citations_for_refs(
    refs: list[str],
    evidence_by_ref: dict[str, _CandidateElement],
) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    for ref in refs:
        element = evidence_by_ref.get(ref)
        if element is not None:
            citations.append(element.citation())
    return citations


def _refs_for_citations(
    citations: list[dict[str, Any]],
    evidence_by_ref: dict[str, _CandidateElement],
) -> list[str]:
    refs: list[str] = []
    for cite in citations:
        ref = cite.get("evidence_ref")
        if isinstance(ref, str) and ref in evidence_by_ref and ref not in refs:
            refs.append(ref)
    return refs


def _rank_candidates(candidates: list[_CandidateElement]) -> list[_CandidateElement]:
    label_weight = {
        "table": 1.0,
        "chart": 0.95,
        "picture": 0.85,
        "formula": 0.8,
        "text": 0.75,
        "section_header": 0.6,
        "text_layer_page": 0.5,
        "page": 0.1,
    }

    def key(c: _CandidateElement) -> tuple[float, float]:
        return (label_weight.get(c.label, 0.65), c.score)

    return sorted(candidates, key=key, reverse=True)


def _dedupe_candidates(candidates: list[_CandidateElement]) -> list[_CandidateElement]:
    out: list[_CandidateElement] = []
    seen: set[tuple[int, int, int, int, int]] = set()
    for cand in candidates:
        key = (
            cand.page,
            int(cand.bbox[0] * 1000),
            int(cand.bbox[1] * 1000),
            int(cand.bbox[2] * 1000),
            int(cand.bbox[3] * 1000),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(cand)
    return out


def _select_by_refs(
    candidates: list[_CandidateElement],
    refs: list[str],
    max_elements: int,
) -> list[_CandidateElement]:
    by_ref = {c.ref: c for c in candidates}
    selected: list[_CandidateElement] = []
    for ref in refs:
        cand = by_ref.get(ref)
        if cand is not None and cand not in selected:
            selected.append(cand)
        if len(selected) >= max_elements:
            break
    if not selected:
        selected = candidates[:max_elements]
    return selected[:max_elements]


def _normalize_bbox(
    raw: Any,
    *,
    width: int,
    height: int,
) -> tuple[float, float, float, float] | None:
    if not (isinstance(raw, list | tuple) and len(raw) == 4):
        return None
    try:
        x0, y0, x1, y1 = (float(v) for v in raw)
    except (TypeError, ValueError):
        return None
    if width > 0 and height > 0 and max(abs(x0), abs(y0), abs(x1), abs(y1)) > 1.0:
        x0, x1 = x0 / width, x1 / width
        y0, y1 = y0 / height, y1 / height
    return _clamp_bbox((x0, y0, x1, y1))


def _clamp_bbox(
    bbox: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = bbox
    x0 = max(0.0, min(1.0, x0))
    y0 = max(0.0, min(1.0, y0))
    x1 = max(0.0, min(1.0, x1))
    y1 = max(0.0, min(1.0, y1))
    if x1 <= x0:
        x1 = min(1.0, x0 + 0.01)
    if y1 <= y0:
        y1 = min(1.0, y0 + 0.01)
    return (x0, y0, x1, y1)


def _fallback_pages(valid_pages: list[int], n: int, *, offset: int) -> list[int]:
    if not valid_pages:
        return [1]
    start = (offset * n) % len(valid_pages)
    rotated = valid_pages[start:] + valid_pages[:start]
    return rotated[:n]


def _answer_images(
    elements: list[_CandidateElement],
    selected_pages: list[int],
    page_entries: list[_PageEntry],
) -> list[Path] | None:
    images: list[Path] = []
    for element in elements:
        if element.crop_ref:
            p = Path(element.crop_ref)
            if p.exists():
                images.append(p)
    if images:
        return images[:_DEFAULT_MAX_ELEMENTS]
    page_by_num = {p.page: p.path for p in page_entries if not p.is_summary and p.path.exists()}
    for page in selected_pages:
        path = page_by_num.get(page)
        if path is not None and path not in images:
            images.append(path)
    return images[:_DEFAULT_MAX_ELEMENTS] or None


def _majority_sample_index(samples: list[_AnswerSample]) -> int | None:
    normalized: dict[str, list[int]] = {}
    for idx, sample in enumerate(samples):
        key = _normalize_answer(sample.answer)
        normalized.setdefault(key, []).append(idx)
    if not normalized:
        return None
    key, indices = max(normalized.items(), key=lambda item: len(item[1]))
    if not key:
        return None
    if len(indices) >= 2 or len(samples) == 1:
        return indices[0]
    return None


def _normalize_answer(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _count_tool_calls(steps: list[TrajectoryStep]) -> int:
    return sum(1 for step in steps if step.tool is not None or step.action == "tool_call")


def _shorten(text: str | None, limit: int) -> str:
    if not text:
        return ""
    one_line = str(text).strip().replace("\n", " ")
    return one_line[:limit]


__all__ = ["DocLensAgent"]
