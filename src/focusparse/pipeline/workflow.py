"""FocusWorkflow — the top-level workflow tying all stages together.

Phase 2 skeleton (this file): `FocusWorkflow.run` wires the stages end-to-end
using deterministic placeholders for plan / route_pages / propose_regions /
inspect / expand_context / verify, with one real VLM call in the reasoner.
Sub-phases 2c–2f progressively replace each placeholder.

`SimpleBaselineAgent` is the parser-bench reproducibility runner (unchanged).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from focusparse.evidence.packet import EvidencePacket
from focusparse.models.base import ModelClient, ModelResponse
from focusparse.pipeline.events import (
    AnswerEvent,
    EvidenceEvent,
    PagesEvent,
    PlanEvent,
    QuestionEvent,
    RegionsEvent,
    VerdictEvent,
)
from focusparse.pipeline.expander import expand_context
from focusparse.pipeline.inspector import inspect_regions
from focusparse.pipeline.localizer import propose_regions
from focusparse.pipeline.planner import plan_question
from focusparse.pipeline.reasoner import answer_from_evidence
from focusparse.pipeline.router import route_pages
from focusparse.pipeline.verifier import verify_answer
from focusparse.tools.get_text_layer import GetTextLayerInput, get_text_layer
from focusparse.traces.recorder import RunTrace, TrajectoryRecorder, TrajectoryStep

if TYPE_CHECKING:
    from focusparse._parser_bench import BenchmarkExample


# Default retry budget. The verifier loop is **opt-in by default** as of
# the 2026-04-27 n=30 A/B (see MEMORY.md). With `max_retries=2` the loop
# fired on 67% of examples but only 9% of retries flipped the verdict,
# while diluting region_recall (-0.08), region_precision (-0.16), and
# bbox_iou_mean (-0.08) — the `retry_localization` action lowers the
# confidence threshold which surfaces noisier boxes. Items 4 (region
# reranker) and 5 (evidence-graph expansion) attack the same problem
# more surgically; flip the default back to a positive integer after
# one of them shows a measurable improvement on a real validation slice.
_DEFAULT_MAX_RETRIES = 0

# Knobs the retry loop tweaks per action. Values match (and float as)
# the localizer's / expander's defaults — initial passes use these,
# retries tighten or widen them.
_DEFAULT_LAYOUT_CONFIDENCE_THRESHOLD = 0.3
_LOCALIZATION_RETRY_FACTOR = 0.7  # multiplied each retry → more boxes surface

_DEFAULT_ADJACENCY_PAD = 0.08
_EXPAND_RETRY_FACTOR = 1.5  # multiplied each retry → wider neighbor net
_MAX_ADJACENCY_PAD = 0.30  # cap so the pad stays meaningful


@dataclass
class WorkflowResult:
    answer: str
    citations: list[dict[str, Any]]
    trace: RunTrace
    telemetry: dict[str, Any]


class FocusWorkflow:
    """The 6-stage lens workflow.

    Constructor accepts `backend_client` directly for Phase 2 skeleton. Later
    sub-phases swap this for `tier_router.client_for(role)` once escalation
    and per-stage tiering is wired.
    """

    def __init__(
        self,
        *,
        backend_client: ModelClient,
        config: Any = None,
        tier_router: Any = None,
        cache: Any = None,
        tools: Any = None,
        max_retries: int = _DEFAULT_MAX_RETRIES,
    ) -> None:
        self.backend_client = backend_client
        self.config = config
        self.tier_router = tier_router
        self.cache = cache
        self.tools = tools
        # `max_retries` caps the verifier→retry loop. 0 reverts the workflow
        # to the pre-2026-04-27 cascade (no loops); the default lets the
        # verifier act as a controller, not just a judge.
        self.max_retries = max_retries

    def _client_for(self, role: str) -> ModelClient | None:
        """Resolve a role-scoped client via `tier_router`, else return None.

        Used by non-reasoner stages that may or may not have a cheap/mid-tier
        client wired. The reasoner still uses `self.backend_client` directly
        so existing `FocusWorkflow(backend_client=...)` call sites keep
        working without a tier router.
        """
        if self.tier_router is None:
            return None
        return self.tier_router.client_for(role)

    def _layout_endpoint_url(self) -> str | None:
        """Resolve the layout endpoint URL from config, else let the tool default."""
        endpoints = getattr(self.config, "endpoints", None) if self.config else None
        if not endpoints:
            return None
        layout = endpoints.get("layout") if isinstance(endpoints, dict) else None
        if layout is None:
            return None
        return getattr(layout, "url", None)

    def _layout_cache_dir(self) -> Path | None:
        """Resolve the on-disk cache dir for layout responses.

        Defaults to `<config.cache.root>/layout`; returns None when no cache
        config is present so tests + ephemeral runs stay uncached.
        """
        return self._role_cache_dir("layout")

    def _text_index_cache_dir(self) -> Path | None:
        """Resolve the on-disk cache dir for per-doc FTS indexes."""
        return self._role_cache_dir("text_index")

    def _text_layer_cache_dir(self) -> Path | None:
        """Resolve the on-disk cache dir for native PDF text-layer extracts."""
        return self._role_cache_dir("text_layer")

    def _role_cache_dir(self, name: str) -> Path | None:
        cache_cfg = getattr(self.config, "cache", None) if self.config else None
        if cache_cfg is None:
            return None
        root = getattr(cache_cfg, "root", None)
        if not root:
            return None
        return Path(root) / name

    async def run(
        self,
        example: BenchmarkExample,
        images: list[Path],
        *,
        protocol: str = "focus",
        output_dir: Path | None = None,
        pdf_path: Path | None = None,
    ) -> WorkflowResult:
        del output_dir  # unused in skeleton
        recorder = TrajectoryRecorder(example_id=example.id, question=example.question)
        recorder.set_plan({"agent": "focus", "protocol": protocol, "n_images": len(images)})
        step_counter = _StepCounter()

        doc_id = _infer_doc_id(example)
        pages_available = len(example.page_images or [])
        domain = getattr(example, "domain", None)
        domain_str = str(domain) if domain is not None else None
        question_event = QuestionEvent(
            example_id=example.id,
            question=example.question,
            doc_id=doc_id,
            pages_available=pages_available,
            domain=domain_str,
        )

        budget = getattr(self.config, "budget", None) if self.config is not None else None
        planner_client = self._client_for("planner")

        # --- PLAN ----------------------------------------------------------
        plan, plan_response = await plan_question(
            question_event,
            budget=budget,
            backend_client=planner_client,
            domain=domain_str,
        )
        recorder.record(
            TrajectoryStep(
                step_index=step_counter.next(),
                stage="plan",
                tier=("cheap" if plan_response is not None else "skeleton"),
                action=("llm_call" if plan_response is not None else "deterministic"),
                args={
                    "question_family": plan.question_family,
                    "routing_policy": plan.routing_policy,
                    "budget_class": plan.budget_class,
                },
                obs_summary=(
                    plan_response.text[:200]
                    if plan_response is not None and plan_response.text
                    else None
                ),
                tokens_in=(plan_response.tokens_in if plan_response is not None else 0),
                tokens_out=(plan_response.tokens_out if plan_response is not None else 0),
                latency_ms=(plan_response.latency_ms if plan_response is not None else 0),
                usd=(plan_response.usd if plan_response is not None else None),
            )
        )

        # Build the page->image map up front so the router can route on real
        # page numbers (parsed from filenames) rather than positional indices.
        images_by_page = _images_by_page(example, images)
        page_universe = sorted(images_by_page.keys())

        # --- ROUTE_PAGES ---------------------------------------------------
        pages_text = await _extract_pages_text(
            pdf_path=pdf_path,
            pages=page_universe,
            cache_dir=self._text_layer_cache_dir(),
        )
        pages = await route_pages(
            question_event,
            plan,
            pages=page_universe,
            pages_text=pages_text,
            text_index_cache_dir=self._text_index_cache_dir(),
        )
        n_text_pages = sum(1 for t in (pages_text or {}).values() if t)
        route_tier = "text_fts" if pages_text else "skeleton"
        recorder.record(
            TrajectoryStep(
                step_index=step_counter.next(),
                stage="route_pages",
                tier=route_tier,
                action="deterministic",
                args={
                    "candidates": [pc.page for pc in pages.candidates],
                    "n_text_pages": n_text_pages,
                },
            )
        )

        # --- LOCALIZE / INSPECT / EXPAND (initial pass) -------------------
        confidence_threshold = _DEFAULT_LAYOUT_CONFIDENCE_THRESHOLD
        adjacency_pad = _DEFAULT_ADJACENCY_PAD

        regions = await self._run_localize(
            question_event,
            plan,
            pages,
            images_by_page=images_by_page,
            confidence_threshold=confidence_threshold,
            recorder=recorder,
            step_counter=step_counter,
        )
        evidence = await self._run_inspect(
            question_event,
            plan,
            regions,
            images_by_page=images_by_page,
            pdf_path=pdf_path,
            recorder=recorder,
            step_counter=step_counter,
        )
        evidence = await self._run_expand(
            evidence,
            regions=regions,
            pdf_path=pdf_path,
            adjacency_pad=adjacency_pad,
            recorder=recorder,
            step_counter=step_counter,
        )

        # --- ANSWER + VERIFY (initial pass) -------------------------------
        answer_event, reasoner_response = await self._run_answer(
            question_event,
            evidence,
            escalation_hint=None,
            recorder=recorder,
            step_counter=step_counter,
        )
        verifier_client = self._client_for("verifier")
        verdict, verify_response = await self._run_verify(
            question_event,
            evidence,
            answer_event,
            backend_client=verifier_client,
            recorder=recorder,
            step_counter=step_counter,
        )

        # --- RETRY LOOP ----------------------------------------------------
        # The verifier acts as a controller, not just a judge. The initial
        # verdict is always classified (accept / abstain / retry-of-some-kind).
        # When the verdict needs a retry but `retries_used == max_retries`,
        # we terminate as "exhausted". This shape keeps the initial-accept
        # path working even when `max_retries=0` (the default since the
        # 2026-04-27 n=30 A/B revealed the loop hurts more than it helps
        # without a smarter retry mutation).
        initial_supported = verdict.supported
        retries_used = 0
        loop_terminated = ""  # set in the loop body before break
        escalation_hint: str | None = None

        while True:
            action = verdict.next_action
            if action == "accept":
                loop_terminated = "accepted"
                break
            if action == "abstain":
                # Replace the answer with a typed abstention so downstream
                # scoring (which checks for abstention keywords) can match.
                from focusparse.pipeline.events import AnswerEvent as _AnswerEvent

                answer_event = _AnswerEvent(
                    answer="Unanswerable",
                    citations=[],
                    confidence=verdict.confidence,
                    reasoning_summary=verdict.reason,
                )
                loop_terminated = "abstained"
                break

            # Verdict wants a retry of some kind. Honor the budget: when we
            # can't retry, surface the current answer + flag exhaustion so
            # the trace shows the verifier wasn't satisfied.
            if retries_used >= self.max_retries:
                loop_terminated = "exhausted"
                break

            retries_used += 1

            if action == "retry_localization":
                confidence_threshold *= _LOCALIZATION_RETRY_FACTOR
                regions = await self._run_localize(
                    question_event,
                    plan,
                    pages,
                    images_by_page=images_by_page,
                    confidence_threshold=confidence_threshold,
                    recorder=recorder,
                    step_counter=step_counter,
                    retry_attempt=retries_used,
                )
                # Localization changed → packets are stale; re-run inspect+expand.
                evidence = await self._run_inspect(
                    question_event,
                    plan,
                    regions,
                    images_by_page=images_by_page,
                    pdf_path=pdf_path,
                    recorder=recorder,
                    step_counter=step_counter,
                    retry_attempt=retries_used,
                )
                evidence = await self._run_expand(
                    evidence,
                    regions=regions,
                    pdf_path=pdf_path,
                    adjacency_pad=adjacency_pad,
                    recorder=recorder,
                    step_counter=step_counter,
                    retry_attempt=retries_used,
                )
            elif action == "expand_context":
                adjacency_pad = min(adjacency_pad * _EXPAND_RETRY_FACTOR, _MAX_ADJACENCY_PAD)
                evidence = await self._run_expand(
                    evidence,
                    regions=regions,
                    pdf_path=pdf_path,
                    adjacency_pad=adjacency_pad,
                    recorder=recorder,
                    step_counter=step_counter,
                    retry_attempt=retries_used,
                )
            elif action == "escalate_reasoner":
                # No state change — just feed the verifier's reason into the
                # next reasoner call so it knows what to address.
                escalation_hint = verdict.reason
            else:
                # Unknown action (future verifier extension) — accept the
                # current answer rather than thrash. Trace shows the action
                # via the verify step's args["next_action"].
                loop_terminated = "accepted"
                break

            # Always re-run answer + verify after a retry. The new verdict
            # decides whether the loop continues.
            answer_event, reasoner_response = await self._run_answer(
                question_event,
                evidence,
                escalation_hint=escalation_hint,
                recorder=recorder,
                step_counter=step_counter,
                retry_attempt=retries_used,
            )
            verdict, verify_response = await self._run_verify(
                question_event,
                evidence,
                answer_event,
                backend_client=verifier_client,
                recorder=recorder,
                step_counter=step_counter,
                retry_attempt=retries_used,
            )

        # `loop_retry_helped`: did the retries flip the verdict from
        # unsupported → supported? Null when no retries fired (caller
        # treats null as "not measured", same as the StageMetrics block).
        loop_retry_helped: bool | None = None
        if retries_used > 0:
            loop_retry_helped = (not initial_supported) and verdict.supported

        # Convert packet-id citations back to {page, bbox} dicts.
        citations = _citations_from_packets(answer_event.citations, evidence.packets)
        trace = recorder.finalize(answer=answer_event.answer, citations=citations)

        telemetry = _make_telemetry(reasoner_response)
        telemetry["retries_used"] = retries_used
        telemetry["loop_terminated"] = loop_terminated
        telemetry["loop_retry_helped"] = loop_retry_helped
        return WorkflowResult(
            answer=answer_event.answer,
            citations=citations,
            trace=trace,
            telemetry=telemetry,
        )

    # -- per-stage runners (used by both initial cascade and retry loop) --

    async def _run_localize(
        self,
        question_event: QuestionEvent,
        plan: PlanEvent,
        pages: PagesEvent,
        *,
        images_by_page: dict[int, Path],
        confidence_threshold: float,
        recorder: TrajectoryRecorder,
        step_counter: _StepCounter,
        retry_attempt: int = 0,
    ) -> RegionsEvent:
        regions = await propose_regions(
            question_event,
            plan,
            pages,
            images_by_page=images_by_page,
            layout_endpoint_url=self._layout_endpoint_url(),
            cache_dir=self._layout_cache_dir(),
            confidence_threshold=confidence_threshold,
        )
        n_fallback_pages = sum(
            1 for r in regions.candidates if "skeleton_full_page" in r.supporting_signals
        )
        recorder.record(
            TrajectoryStep(
                step_index=step_counter.next(),
                stage="localize",
                tier=(
                    "layout_detect" if n_fallback_pages < len(regions.candidates) else "skeleton"
                ),
                action="deterministic",
                args={
                    "n_regions": len(regions.candidates),
                    "n_fallback_pages": n_fallback_pages,
                    "confidence_threshold": confidence_threshold,
                    "retry_attempt": retry_attempt,
                },
            )
        )
        return regions

    async def _run_inspect(
        self,
        question_event: QuestionEvent,
        plan: PlanEvent,
        regions: RegionsEvent,
        *,
        images_by_page: dict[int, Path],
        pdf_path: Path | None,
        recorder: TrajectoryRecorder,
        step_counter: _StepCounter,
        retry_attempt: int = 0,
    ) -> EvidenceEvent:
        evidence = await inspect_regions(
            question_event,
            plan,
            regions,
            images_by_page=images_by_page,
            pdf_path=pdf_path,
            crop_cache_dir=self._role_cache_dir("crops"),
            text_layer_cache_dir=self._text_layer_cache_dir(),
        )
        n_real_packets = sum(
            1 for p in evidence.packets if p.provenance.tool != "skeleton_inspector_fallback"
        )
        inspect_tier = "deterministic" if pdf_path is not None else "skeleton"
        recorder.record(
            TrajectoryStep(
                step_index=step_counter.next(),
                stage="inspect",
                tier=inspect_tier,
                action="tool_call",
                tool="deterministic_inspector",
                args={
                    "n_packets": len(evidence.packets),
                    "n_real_packets": n_real_packets,
                    "retry_attempt": retry_attempt,
                },
            )
        )
        return evidence

    async def _run_expand(
        self,
        evidence: EvidenceEvent,
        *,
        regions: RegionsEvent,
        pdf_path: Path | None,
        adjacency_pad: float,
        recorder: TrajectoryRecorder,
        step_counter: _StepCounter,
        retry_attempt: int = 0,
    ) -> EvidenceEvent:
        expanded = await expand_context(
            evidence,
            regions=regions,
            pdf_path=pdf_path,
            crop_cache_dir=self._role_cache_dir("crops"),
            adjacency_pad=adjacency_pad,
        )
        n_with_neighbors = sum(1 for p in expanded.packets if p.linked_crop_refs)
        n_neighbors = sum(len(p.linked_crop_refs) for p in expanded.packets)
        expand_tier = "deterministic" if n_with_neighbors > 0 else "skeleton"
        recorder.record(
            TrajectoryStep(
                step_index=step_counter.next(),
                stage="expand_context",
                tier=expand_tier,
                action="deterministic",
                args={
                    "n_packets": len(expanded.packets),
                    "n_with_neighbors": n_with_neighbors,
                    "n_neighbors_attached": n_neighbors,
                    "adjacency_pad": adjacency_pad,
                    "retry_attempt": retry_attempt,
                },
            )
        )
        return expanded

    async def _run_answer(
        self,
        question_event: QuestionEvent,
        evidence: EvidenceEvent,
        *,
        escalation_hint: str | None,
        recorder: TrajectoryRecorder,
        step_counter: _StepCounter,
        retry_attempt: int = 0,
    ) -> tuple[AnswerEvent, ModelResponse]:
        answer_event, reasoner_response = await answer_from_evidence(
            question_event,
            evidence,
            backend_client=self.backend_client,
            escalation_hint=escalation_hint,
        )
        recorder.record(
            TrajectoryStep(
                step_index=step_counter.next(),
                stage="answer",
                tier="reasoner",
                action="llm_call",
                args={
                    "n_packets": len(evidence.packets),
                    "retry_attempt": retry_attempt,
                    "had_escalation_hint": bool(escalation_hint),
                },
                obs_summary=(reasoner_response.text[:200] if reasoner_response.text else None),
                tokens_in=reasoner_response.tokens_in,
                tokens_out=reasoner_response.tokens_out,
                latency_ms=reasoner_response.latency_ms,
                usd=reasoner_response.usd,
                confidence=answer_event.confidence,
            )
        )
        return answer_event, reasoner_response

    async def _run_verify(
        self,
        question_event: QuestionEvent,
        evidence: EvidenceEvent,
        answer_event: AnswerEvent,
        *,
        backend_client: ModelClient | None,
        recorder: TrajectoryRecorder,
        step_counter: _StepCounter,
        retry_attempt: int = 0,
    ) -> tuple[VerdictEvent, ModelResponse | None]:
        verdict, verify_response = await verify_answer(
            question_event,
            evidence,
            answer_event,
            backend_client=backend_client,
        )
        recorder.record(
            TrajectoryStep(
                step_index=step_counter.next(),
                stage="verify",
                tier=("mid" if verify_response is not None else "skeleton"),
                action=("llm_call" if verify_response is not None else "deterministic"),
                args={
                    "next_action": verdict.next_action,
                    "supported": verdict.supported,
                    "retry_attempt": retry_attempt,
                },
                obs_summary=(
                    verify_response.text[:200]
                    if verify_response is not None and verify_response.text
                    else None
                ),
                tokens_in=(verify_response.tokens_in if verify_response is not None else 0),
                tokens_out=(verify_response.tokens_out if verify_response is not None else 0),
                latency_ms=(verify_response.latency_ms if verify_response is not None else 0),
                usd=(verify_response.usd if verify_response is not None else None),
                confidence=verdict.confidence,
            )
        )
        return verdict, verify_response


# ---------------------------------------------------------------------------
# Helpers (pure, unit-testable)
# ---------------------------------------------------------------------------


class _StepCounter:
    """Monotonic step_index counter shared across the cascade + retry loop.

    Replaces the hardcoded `step_index=0..6` from the pre-loop workflow.
    Every `TrajectoryStep` gets a unique index so retry steps don't
    overwrite the indices of the initial pass.
    """

    def __init__(self) -> None:
        self._n = 0

    def next(self) -> int:
        idx = self._n
        self._n += 1
        return idx


def _infer_doc_id(example: BenchmarkExample) -> str:
    """Best-effort doc id: prefer source_pdf stem, fall back to example id."""
    src = getattr(example, "source_pdf", None)
    if src:
        return Path(src).stem
    return example.id


def _images_by_page(
    example: BenchmarkExample,
    images: list[Path],
) -> dict[int, Path]:
    """Map 1-indexed page number -> local PNG path.

    We prefer parsing the page number from the filename (parser-bench layout
    is `..._page_NNNN_300dpi.png`) so the map is robust to protocols that
    reorder or filter pages. Falls back to positional index when the filename
    doesn't match the pattern.
    """
    mapping: dict[int, Path] = {}
    for idx, img in enumerate(images):
        page = _page_number_from_filename(img.name)
        if page is None:
            page = idx + 1
        mapping[page] = img
    return mapping


_PAGE_IN_FILENAME_RE = re.compile(r"_page_(\d+)")


def _page_number_from_filename(name: str) -> int | None:
    m = _PAGE_IN_FILENAME_RE.search(name)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


async def _extract_pages_text(
    *,
    pdf_path: Path | None,
    pages: list[int],
    cache_dir: Path | None,
) -> dict[int, str] | None:
    """Return per-page plain text for `pages`, or None when no PDF is supplied.

    Pages whose native text layer is empty (scanned/image-only) come back
    with an empty string rather than being omitted — the router wants a
    stable page universe so `pages_text_no_matches` means "FTS matched
    nothing" rather than "we forgot this page existed".

    Silently returns None when `pdf_path` is None or missing on disk. We
    deliberately don't propagate FileNotFoundError here: the workflow has
    to keep running with a skeleton router in that case, not crash the run.
    """
    if pdf_path is None:
        return None
    resolved = Path(pdf_path)
    if not resolved.exists():
        return None

    pages_text: dict[int, str] = {}
    for page in pages:
        try:
            out = await get_text_layer(
                GetTextLayerInput(doc_path=str(resolved), page=page),
                cache_dir=cache_dir,
            )
        except (ValueError, FileNotFoundError):
            # Out-of-range or race-y disappearance: keep the workflow alive,
            # mark this page as empty so FTS still sees it in the universe.
            pages_text[page] = ""
            continue
        pages_text[page] = out.text
    return pages_text


def _citations_from_packets(
    packet_ids: list[str],
    packets: list[EvidencePacket],
) -> list[dict[str, Any]]:
    """Translate reasoner citation refs -> [{page, bbox: [x0,y0,x1,y1]}]."""
    by_id = {p.packet_id: p for p in packets}
    out: list[dict[str, Any]] = []
    for pid in packet_ids:
        pkt = by_id.get(pid)
        if pkt is None:
            continue
        out.append({"page": pkt.page, "bbox": list(pkt.bbox_norm)})
    return out


def _make_telemetry(response: ModelResponse) -> dict[str, Any]:
    return {
        "tokens_in": response.tokens_in,
        "tokens_out": response.tokens_out,
        "usd": response.usd,
        "latency_ms": response.latency_ms,
        "raw_response_len": len(response.text or ""),
    }


# ---------------------------------------------------------------------------
# SimpleBaselineAgent
# ---------------------------------------------------------------------------

_SIMPLE_SYSTEM_PROMPT = (
    "You are answering a question about a document using the provided page image(s). "
    "Return strict JSON with keys `answer` and `citations`. "
    "`answer` is the answer string (or the literal word 'Unanswerable'). "
    '`citations` is a list of objects `{"page": <int>, "bbox": [x0, y0, x1, y1]}` '
    "with normalized [0,1] coordinates pointing to the region that supports the answer. "
    "If no region applies, return an empty citations list. Do not add extra keys."
)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


class SimpleBaselineAgent:
    """Single-shot VLM baseline used for parser-bench reproducibility checks.

    Protocol handling is the caller's job — `images` is already prepared for
    `full_doc` / `oracle_page` / `oracle_crop`. The agent does one VLM call
    and records a single `TrajectoryStep`.
    """

    def __init__(self, *, backend_client: ModelClient, protocol: str) -> None:
        self.backend_client = backend_client
        self.protocol = protocol

    async def run(
        self,
        example: BenchmarkExample,
        images: list[Path],
    ) -> WorkflowResult:
        recorder = TrajectoryRecorder(example_id=example.id, question=example.question)
        recorder.set_plan({"agent": "simple", "protocol": self.protocol, "n_images": len(images)})

        prompt = f"Question: {example.question}"
        response: ModelResponse = await self.backend_client.predict(
            prompt=prompt,
            images=images,
            system=_SIMPLE_SYSTEM_PROMPT,
        )

        answer, citations = _parse_simple_response(response.text)

        recorder.record(
            TrajectoryStep(
                step_index=0,
                stage="simple_answer",
                tier="baseline",
                action="llm_call",
                tool=None,
                args={"protocol": self.protocol, "n_images": len(images)},
                obs_summary=(response.text[:200] if response.text else None),
                tokens_in=response.tokens_in,
                tokens_out=response.tokens_out,
                latency_ms=response.latency_ms,
                usd=response.usd,
            )
        )
        trace = recorder.finalize(answer=answer, citations=citations)

        telemetry = {
            "tokens_in": response.tokens_in,
            "tokens_out": response.tokens_out,
            "usd": response.usd,
            "latency_ms": response.latency_ms,
            "raw_response_len": len(response.text or ""),
        }
        return WorkflowResult(answer=answer, citations=citations, trace=trace, telemetry=telemetry)


def _parse_simple_response(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Extract (answer, citations) from a model response.

    Tolerates: bare JSON, JSON in a ```json fence, or free text (fallback = raw
    text as answer, empty citations). Never raises — a broken response yields
    answer=text, citations=[].
    """
    if not text:
        return "", []

    candidate = text.strip()
    fence = _JSON_FENCE_RE.search(candidate)
    if fence:
        candidate = fence.group(1)
    else:
        # Try to find the first top-level {...} block.
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = candidate[start : end + 1]

    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError:
        return text.strip(), []

    if not isinstance(obj, dict):
        return text.strip(), []

    answer = obj.get("answer", "")
    if not isinstance(answer, str):
        answer = str(answer)

    raw_citations = obj.get("citations", []) or []
    citations: list[dict[str, Any]] = []
    for c in raw_citations:
        if not isinstance(c, dict):
            continue
        page = c.get("page")
        bbox = c.get("bbox")
        if not isinstance(page, int):
            try:
                page = int(page)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
        if not (isinstance(bbox, list) and len(bbox) == 4):
            continue
        try:
            bbox_f = [float(x) for x in bbox]
        except (TypeError, ValueError):
            continue
        citations.append({"page": page, "bbox": bbox_f})

    return answer, citations
