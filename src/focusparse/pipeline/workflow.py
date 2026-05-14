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
from focusparse.pipeline.inspector import _FINE_DETAIL_QUESTION_FAMILIES, inspect_regions
from focusparse.pipeline.localizer import propose_regions
from focusparse.pipeline.planner import plan_question
from focusparse.pipeline.reasoner import answer_from_evidence
from focusparse.pipeline.region_reranker import rerank_regions
from focusparse.pipeline.router import route_pages
from focusparse.pipeline.verifier import verify_answer
from focusparse.tools.get_text_layer import GetTextLayerInput, get_text_layer
from focusparse.traces.recorder import (
    EvidencePacketSummary,
    RunTrace,
    TrajectoryRecorder,
    TrajectoryStep,
)

if TYPE_CHECKING:
    from focusparse._parser_bench import BenchmarkExample


# Default full retry budget. Localization retries stay opt-in after the
# 2026-04-27 n=30 A/B: `max_retries=2` fired on 67% of examples but only
# 9% of retries flipped the verdict, while diluting region_recall (-0.08),
# region_precision (-0.16), and bbox_iou_mean (-0.08). The culprit was the
# `retry_localization` action lowering the confidence threshold and surfacing
# noisier boxes.
_DEFAULT_MAX_RETRIES = 0
# Evidence-only retries are safer: they do not re-run localization, and the
# 2026-05-08 n=148 crop-fallback diagnostic showed 45 wrong examples where the
# verifier asked for `expand_context` after the initial pass. Let the controller
# try one bounded evidence repair by default while keeping localization retries
# behind `max_retries`.
_DEFAULT_MAX_EVIDENCE_RETRIES = 1
# Keep the evidence-only budget for actions that actually mutate evidence.
# `escalate_reasoner` spends another frontier call without improving
# inspect/expand packets, so it stays behind the explicit full-loop budget.
_EVIDENCE_RETRY_ACTIONS = frozenset({"expand_context"})

# Knobs the retry loop tweaks per action. Values match (and float as)
# the localizer's / expander's defaults — initial passes use these,
# retries tighten or widen them.
_DEFAULT_LAYOUT_CONFIDENCE_THRESHOLD = 0.3
_LOCALIZATION_RETRY_FACTOR = 0.7  # multiplied each retry → more boxes surface

_DEFAULT_ADJACENCY_PAD = 0.08
_EXPAND_RETRY_FACTOR = 1.5  # multiplied each retry → wider neighbor net
_MAX_ADJACENCY_PAD = 0.30  # cap so the pad stays meaningful
_RETRY_SELECTION_CONFIDENCE_MARGIN = 0.15
_ABSTAIN_OVERRIDE_MIN_CONFIDENCE = 0.45

# Phase 2 of harness-growth-sprint (2026-05-11): hard-case dispatch for the
# LLM-driven inspector. When `use_react_inspector=True`, the workflow routes
# through the ReAct inspector ONLY for examples where the deterministic top-N
# is most likely to miss — fine-detail visual questions, planner-flagged tiny
# regions, or low-confidence reranks. Other examples stay on the deterministic
# floor (cheaper + faster). The previous behaviour was binary "always ReAct or
# never", which burned cost on every easy example.
_HARD_CASE_RELEVANCE_THRESHOLD = 0.5  # top region rerank below this → "hard"
_HARD_CASE_BUDGET_CLASSES = frozenset({"highres_tiny"})


def _should_use_react_inspector(plan: PlanEvent, regions: RegionsEvent) -> bool:
    """Return True when the example is "hard" enough to warrant the ReAct
    inspector — caller still must check `self.use_react_inspector` is on.

    Triggers (Phase 5 of harness-growth-sprint, 2026-05-11 evening):
      A. ``plan.budget_class == "highres_tiny"`` — the strongest single
         signal (planner explicitly flagged tiny-region / fine-detail).
         Fires alone.
      B. ``plan.question_family`` is in `_FINE_DETAIL_QUESTION_FAMILIES`
         AND the top reranked region's ``relevance`` is below
         ``_HARD_CASE_RELEVANCE_THRESHOLD``. Both must hold.

    Phase 2 (the original) fired on ANY of three triggers (highres_tiny
    OR fine-detail family OR low rerank confidence). The Phase 4 result
    slice analysis showed the trigger was over-firing:

      - hard-case slice (51 ex, fired): 47.1% acc vs 51.0% rebaseline (-3.9pp)
      - deterministic slice (92 ex):     51.1% acc vs 39.1% rebaseline (+12.0pp)

    The dispatcher was net-negative on the slice it fires on; the Phase 4
    +4.1pp overall gain came entirely from the deterministic slice (Phase
    1 chart_to_table gate + Phase 3 per-role expander gating).

    Failure analysis of the 5 react-path losses surfaced two patterns:
      - 2/5 were planner regressions (the planner emitted a different
        ``question_family`` from rebaseline, which flipped trigger B).
      - 3/5 were genuine over-firing — same planner output, but the
        LLM-driven inspector picked different (worse) regions than the
        deterministic top-N would have, including one hallucination on
        a true-``unanswerable`` example.

    Trigger B becomes AND-gated (was OR) to require BOTH the fine-detail
    family signal AND the low-rerank-confidence signal before firing.
    This eliminates the false positives on examples where the planner
    family is fine-detail but the reranker has high confidence (the
    deterministic top-N is already correct on those).

    Predicted firing rate: ~5-15% (vs Phase 2's 35%). The goal is to
    keep only the truly-hard examples where the LLM dispatcher could
    plausibly outperform deterministic top-N.
    """
    if (plan.budget_class or "").strip() in _HARD_CASE_BUDGET_CLASSES:
        return True
    family_is_fine_detail = (plan.question_family or "").strip() in _FINE_DETAIL_QUESTION_FAMILIES
    top = regions.candidates[0] if regions.candidates else None
    rerank_is_low = (
        top is not None
        and top.relevance is not None
        and float(top.relevance) < _HARD_CASE_RELEVANCE_THRESHOLD
    )
    # Phase 5: BOTH signals required (was: either signal sufficient).
    return family_is_fine_detail and rerank_is_low


_VISUAL_READABILITY_RE = re.compile(
    r"\b("
    r"blur(?:ry|red)?|cannot\s+read|can't\s+read|difficult\s+to\s+read|"
    r"fragmented|garbled|illegible|incomplete|low[- ]resolution|not\s+fully\s+readable|"
    r"ocr[- ]?(?:damaged|garbled|poor)|pixelated|too\s+small|unclear|unreadable"
    r")\b",
    re.IGNORECASE,
)
_VISUAL_EVIDENCE_RE = re.compile(
    r"\b(axis|chart|crop|diagram|figure|image|label|ocr|plot|schematic|signal|timing|visual)\b",
    re.IGNORECASE,
)
_FOCUSED_RETRY_SUPPLEMENTAL_CONTEXT_TYPES = frozenset(
    {
        "caption",
        "code",
        "context_window",
        "footnote",
        "key-value region",
        "key_value_region",
        "list-item",
        "list_item",
        "page-header",
        "section-header",
        "section_header",
        "table",
        "text",
        "title",
    }
)
_MAX_FOCUSED_RETRY_SUPPLEMENTAL_PACKETS = 2
_MAX_FOCUSED_RETRY_VISUAL_SIBLINGS = 2
_FOCUSED_RETRY_VISUAL_SIBLING_RE = re.compile(
    r"\b("
    r"gridlines?|layout\s+overview|multiple\s+(?:waveforms?|traces?|panels?)|"
    r"oscilloscope|panel|specific\s+(?:trace|signal|waveform)|"
    r"timing|transition|waveforms?"
    r")\b",
    re.IGNORECASE,
)
_VISUAL_PACKET_TYPES = frozenset(
    {
        "bar_chart",
        "candlestick",
        "chart",
        "curve",
        "diagram",
        "figure",
        "image",
        "line_chart",
        "picture",
        "plot",
    }
)
_ANSWER_TOKEN_RE = re.compile(r"[a-z0-9]+")
_ANSWER_SELECTION_STOPWORDS = frozenset(
    {
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
        "of",
        "on",
        "or",
        "the",
        "to",
        "what",
        "which",
        "with",
    }
)


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
        max_evidence_retries: int = _DEFAULT_MAX_EVIDENCE_RETRIES,
        use_evidence_graph: bool = False,
        auto_zoom: bool = False,
        tool_set: str = "full",
        use_react_inspector: bool = False,
        multi_scale_packets: bool = False,
        chart_to_table_enabled: bool = False,
        allow_layout_endpoint_fallback: bool = True,
        layout_max_retries: int | None = None,
        layout_timeout_s: float | None = None,
        proactive_non_abstain_retry: bool = True,
    ) -> None:
        self.backend_client = backend_client
        self.config = config
        self.tier_router = tier_router
        self.cache = cache
        self.tools = tools
        # `max_retries` caps the full verifier→retry loop, including
        # localization. `max_evidence_retries` gives evidence/reasoning
        # repairs a separate small budget so verifier control is not all-or-
        # nothing.
        self.max_retries = max_retries
        self.max_evidence_retries = max_evidence_retries
        # Item 5: typed evidence-graph expansion. Default off pending a fresh
        # A/B under the post-2026-04-27 scorer (the n=30 regression that
        # gated this off was measured under the pre-fix scorer).
        self.use_evidence_graph = use_evidence_graph
        # Phase 3: auto-zoom tiny regions via run_python (LANCZOS 2× upsample).
        # Default off — needs an A/B before flipping. Visual-reading examples
        # like axis-value-interpolation are the target use case.
        # Forced off when tool_set=="minimal" (run_python is one of the
        # tools removed in that variant).
        self.auto_zoom = auto_zoom and tool_set != "minimal"
        # Headline-table tool-set axis: "minimal" = inspect_region +
        # get_text_layer only; "full" = + expand_context + run_python.
        # When minimal, the expand_context stage is skipped (passthrough)
        # so the +2-tools row of the table is a real ablation, not just
        # a flag that hides expansion.
        if tool_set not in ("minimal", "full"):
            raise ValueError(f"tool_set must be 'minimal' or 'full', got {tool_set!r}")
        self.tool_set = tool_set
        # Phase 6 candidate #1 (Phase 1 of the 2026-05-04 sprint): LLM-driven
        # inspector dispatch. When True, _run_inspect routes through
        # `inspector_react.react_inspect` which lets a mid-tier LLM pick
        # which regions to inspect from the localizer's candidate list.
        # Falls back to deterministic top-N when the LLM is unavailable
        # or returns a malformed plan, so call sites without an
        # inspector_dispatch tier still work.
        self.use_react_inspector = use_react_inspector
        # Phase 6 candidate #6 (sprint Phase 2): Multi-scale evidence packets.
        # When True, the inspector renders both a tight crop and a wider
        # ~30%-padded context crop per region; the reasoner sees both via
        # `EvidencePacket.multi_scale_crops`. Default off pending the n=148
        # A/B (~$3-5 expected cost; ~+2-5pp predicted lift).
        self.multi_scale_packets = multi_scale_packets
        # Phase 6 #7 (sprint Phase 3): chart_to_table extraction. Gated
        # on plan.question_family inside the inspector so it only fires
        # for axis_value_interpolation / candlestick_ohlc_extraction
        # questions — most n=148 examples don't pay this cost.
        self.chart_to_table_enabled = chart_to_table_enabled
        # Production/demo workflows can keep the historical full-page
        # fallback. Research evals flip this off so a transient layout
        # endpoint outage cannot contaminate headline accuracy.
        self.allow_layout_endpoint_fallback = allow_layout_endpoint_fallback
        self.layout_max_retries = layout_max_retries
        self.layout_timeout_s = layout_timeout_s
        # Phase 3d (2026-05-13 sprint): proactive non-abstain retry. When the
        # initial reasoner answer is 'Unanswerable' but the reasoner cited >= 2
        # evidence packets (i.e. it found candidate evidence but gave up on
        # extraction), force one extra reasoner call with a 'do not abstain'
        # hint before letting the verifier see the abstention. On n=148
        # main-stack the lazy_answer_rate is 8.1% (12/148) and every lazy row
        # has a concrete non-null gold — so this is overwhelmingly harness
        # error, not benchmark error. Costs ~+8% of a reasoner call/example.
        self.proactive_non_abstain_retry = proactive_non_abstain_retry

    def _client_for(self, role: str) -> ModelClient | None:
        """Resolve a role-scoped client via `tier_router`, else return None.

        Used by non-reasoner stages that may or may not have a cheap/mid-tier
        client wired. The reasoner still uses `self.backend_client` directly
        so existing `FocusWorkflow(backend_client=...)` call sites keep
        working without a tier router.
        """
        if self.tier_router is None:
            return None
        try:
            return self.tier_router.client_for(role)
        except KeyError:
            # The role isn't configured in `roles:` and no `FOCUSPARSE_TIER_<ROLE>`
            # env var is set. The stage's caller treats `None` as "no client →
            # use the deterministic fallback for this stage" (e.g.
            # `inspector_react` falls back to deterministic top-N). This is
            # safer than crashing the whole example: an unconfigured optional
            # role is a config-coverage gap, not a workflow bug.
            return None

    def _layout_endpoint_url(self) -> str | None:
        """Resolve the layout endpoint URL from config, else let the tool default."""
        endpoints = getattr(self.config, "endpoints", None) if self.config else None
        if not endpoints:
            return None
        layout = endpoints.get("layout") if isinstance(endpoints, dict) else None
        if layout is None:
            return None
        return getattr(layout, "url", None)

    def _layout_endpoint_retries(self) -> int | None:
        """Resolve layout retry count from constructor override or config."""
        if self.layout_max_retries is not None:
            return self.layout_max_retries
        layout = self._layout_endpoint_config()
        return getattr(layout, "retries", None) if layout is not None else None

    def _layout_endpoint_timeout_s(self) -> float | None:
        """Resolve layout timeout from constructor override or config."""
        if self.layout_timeout_s is not None:
            return self.layout_timeout_s
        layout = self._layout_endpoint_config()
        timeout = getattr(layout, "timeout_s", None) if layout is not None else None
        return float(timeout) if timeout is not None else None

    def _layout_endpoint_config(self) -> Any | None:
        endpoints = getattr(self.config, "endpoints", None) if self.config else None
        if not endpoints:
            return None
        return endpoints.get("layout") if isinstance(endpoints, dict) else None

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
        answer_type_attr = getattr(example, "answer_type", None)
        answer_type_str = str(answer_type_attr) if answer_type_attr is not None else None
        question_event = QuestionEvent(
            example_id=example.id,
            question=example.question,
            doc_id=doc_id,
            pages_available=pages_available,
            domain=domain_str,
            answer_type=answer_type_str,
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
        _record_page_artifacts(recorder, images_by_page)

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
        _add_debug_event(
            recorder,
            stage="route_pages",
            event_type="candidate_pages",
            payload={
                "pages": [_page_candidate_to_debug(pc) for pc in pages.candidates],
                "n_text_pages": n_text_pages,
            },
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
        # Query-conditioned rerank between localize and inspect (Phase 2
        # item 4). Skip path when no localizer_rerank tier is wired.
        regions = await self._run_rerank(
            question_event,
            plan,
            regions,
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
            images_by_page=images_by_page,
            adjacency_pad=adjacency_pad,
            recorder=recorder,
            step_counter=step_counter,
            plan=plan,
        )

        # --- ANSWER + VERIFY (initial pass) -------------------------------
        answer_event, reasoner_response = await self._run_answer(
            question_event,
            evidence,
            escalation_hint=None,
            recorder=recorder,
            step_counter=step_counter,
            question_family=plan.question_family,
        )

        # Phase 3d (2026-05-13 sprint): proactive non-abstain retry.
        # When the initial answer is 'Unanswerable' but the reasoner cited
        # at least one packet, the evidence is present and the reasoner gave
        # up on extraction. Re-prompt once with a 'do not abstain' hint
        # before the verifier sees the abstention. Citation-gated so cases
        # with zero citations (the model genuinely saw nothing) do not
        # trigger a hallucination-prone retry. Default-on; gated by a config
        # flag so we can A/B if needed.
        if (
            self.proactive_non_abstain_retry
            and _answer_looks_unanswerable(answer_event.answer)
            and len(answer_event.citations) >= 1
            and len(evidence.packets) >= 1
        ):
            non_abstain_hint = (
                "Your previous answer was 'Unanswerable' but you cited "
                f"{len(answer_event.citations)} evidence packet(s). The "
                "verifier will compare your answer against those packets — "
                "they likely contain the answer. Re-read the cited packets "
                "carefully, look at the attached neighbor / context-window "
                "crops if present, and produce a concrete answer drawn "
                "directly from the packet contents. Only return "
                "'Unanswerable' if you can explicitly confirm that no "
                "relevant data appears in any of the cited packets."
            )
            retry_answer, retry_response = await self._run_answer(
                question_event,
                evidence,
                escalation_hint=non_abstain_hint,
                recorder=recorder,
                step_counter=step_counter,
                retry_attempt=0,
                evidence_scope="full",
                question_family=plan.question_family,
            )
            if not _answer_looks_unanswerable(retry_answer.answer):
                _add_debug_event(
                    recorder,
                    stage="answer",
                    event_type="selection",
                    retry_attempt=0,
                    payload={
                        "selected": "proactive_non_abstain_retry",
                        "discarded_answer": answer_event.answer,
                        "discarded_confidence": answer_event.confidence,
                        "selected_answer": retry_answer.answer,
                        "selected_confidence": retry_answer.confidence,
                        "n_cited_packets": len(answer_event.citations),
                    },
                )
                answer_event = retry_answer
                reasoner_response = retry_response

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
        initial_answer_text = answer_event.answer
        retries_used = 0
        evidence_retries_used = 0
        tool_retry_used = False
        loop_terminated = ""  # set in the loop body before break
        escalation_hint: str | None = None
        answer_evidence = evidence
        best_unsupported_answer: AnswerEvent | None = None
        best_unsupported_evidence: EvidenceEvent | None = None
        if not verdict.supported:
            best_unsupported_answer = answer_event
            best_unsupported_evidence = answer_evidence

        while True:
            action = verdict.next_action
            if action == "accept":
                loop_terminated = "accepted"
                break
            if action == "abstain":
                if _should_keep_best_unsupported_on_retry_abstain(
                    best_unsupported_answer,
                    question_event=question_event,
                    retries_used=retries_used,
                ):
                    _add_debug_event(
                        recorder,
                        stage="answer",
                        event_type="selection",
                        retry_attempt=retries_used,
                        payload={
                            "selected": "best_unsupported",
                            "reason": "retry_abstain_after_evidence_repair",
                            "selected_answer": best_unsupported_answer.answer,
                            "selected_confidence": best_unsupported_answer.confidence,
                            "discarded_answer": answer_event.answer,
                            "discarded_confidence": answer_event.confidence,
                        },
                    )
                    answer_event = best_unsupported_answer
                    if best_unsupported_evidence is not None:
                        answer_evidence = best_unsupported_evidence
                    loop_terminated = "exhausted"
                    break
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
            retry_budget = self._retry_budget_for_action(action)
            if _should_allow_reasoner_shape_retry(
                action=action,
                answer=answer_event,
                verdict=verdict,
                question_event=question_event,
                max_evidence_retries=self.max_evidence_retries,
            ):
                retry_budget = max(retry_budget, self.max_evidence_retries)
            if retries_used >= retry_budget:
                loop_terminated = "exhausted"
                break

            retries_used += 1
            if action in _EVIDENCE_RETRY_ACTIONS:
                evidence_retries_used += 1

            if action == "retry_localization":
                tool_retry_used = True
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
                # Re-rank the new region set so the retry's top-N is also
                # query-conditioned, not just lower-confidence boxes.
                regions = await self._run_rerank(
                    question_event,
                    plan,
                    regions,
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
                    images_by_page=images_by_page,
                    adjacency_pad=adjacency_pad,
                    recorder=recorder,
                    step_counter=step_counter,
                    retry_attempt=retries_used,
                    plan=plan,
                )
                retry_answer_evidence = evidence
            elif action == "expand_context":
                tool_retry_used = True
                adjacency_pad = min(adjacency_pad * _EXPAND_RETRY_FACTOR, _MAX_ADJACENCY_PAD)
                verifier_missing_context = _verifier_missing_context(verdict)
                target_packet_ids = _verifier_target_packet_ids(
                    verdict,
                    valid_packet_ids={packet.packet_id for packet in evidence.packets},
                ) or list(answer_event.citations)
                retry_plan = _plan_with_extra_evidence_types(plan, verifier_missing_context)
                retry_visual_zoom = _verifier_requests_visual_readability_retry(
                    verdict,
                    target_packet_ids=target_packet_ids,
                )
                evidence = await self._run_expand(
                    evidence,
                    regions=regions,
                    pdf_path=pdf_path,
                    images_by_page=images_by_page,
                    adjacency_pad=adjacency_pad,
                    recorder=recorder,
                    step_counter=step_counter,
                    retry_attempt=retries_used,
                    plan=retry_plan,
                    verifier_reason=verdict.reason,
                    verifier_missing_context=verifier_missing_context,
                    target_packet_ids=target_packet_ids,
                    retry_visual_zoom=retry_visual_zoom,
                )
                retry_answer_evidence = _focused_retry_evidence(
                    evidence,
                    target_packet_ids,
                    cited_packet_ids=list(answer_event.citations),
                    verifier_reason=verdict.reason,
                )
                # The retry answer should know what the verifier thought was
                # missing. When there are no cited/target packets, the explicit
                # empty target list keeps expansion from sweeping every packet;
                # the hint still gives the reasoner a focused repair instruction.
                escalation_hint = verdict.reason
            elif action == "escalate_reasoner":
                # No state change — just feed the verifier's reason into the
                # next reasoner call so it knows what to address.
                retry_answer_evidence = evidence
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
                retry_answer_evidence,
                escalation_hint=escalation_hint,
                recorder=recorder,
                step_counter=step_counter,
                retry_attempt=retries_used,
                evidence_scope=_evidence_scope(evidence, retry_answer_evidence),
                question_family=plan.question_family,
            )
            answer_evidence = retry_answer_evidence
            verdict, verify_response = await self._run_verify(
                question_event,
                answer_evidence,
                answer_event,
                backend_client=verifier_client,
                recorder=recorder,
                step_counter=step_counter,
                retry_attempt=retries_used,
            )
            if not verdict.supported and _is_better_unsupported_answer(
                answer_event,
                best_unsupported_answer,
                question_text=question_event.question,
            ):
                best_unsupported_answer = answer_event
                best_unsupported_evidence = answer_evidence

        # `loop_retry_helped`: did the retries flip the verdict from
        # unsupported → supported? Null when no retries fired (caller
        # treats null as "not measured", same as the StageMetrics block).
        loop_retry_helped: bool | None = None
        if retries_used > 0:
            loop_retry_helped = (not initial_supported) and verdict.supported

        if (
            loop_terminated == "exhausted"
            and not verdict.supported
            and best_unsupported_answer is not None
            and best_unsupported_evidence is not None
            and best_unsupported_answer is not answer_event
        ):
            _add_debug_event(
                recorder,
                stage="answer",
                event_type="selection",
                retry_attempt=retries_used,
                payload={
                    "selected": "best_unsupported",
                    "reason": "retry_exhausted_without_support",
                    "selected_answer": best_unsupported_answer.answer,
                    "selected_confidence": best_unsupported_answer.confidence,
                    "discarded_answer": answer_event.answer,
                    "discarded_confidence": answer_event.confidence,
                },
            )
            answer_event = best_unsupported_answer
            evidence = best_unsupported_evidence
        else:
            evidence = answer_evidence

        # Convert packet-id citations back to {page, bbox} dicts.
        citations = _citations_from_packets(answer_event.citations, evidence.packets)
        # Trace schema v2+ (2026-05-04): snapshot the final evidence the
        # reasoner saw so the per-trace HTML viewer can render packets +
        # crops without re-running the pipeline.
        recorder.set_evidence_snapshot([_packet_to_summary(p) for p in evidence.packets])
        trace = recorder.finalize(answer=answer_event.answer, citations=citations)

        telemetry = _make_telemetry(reasoner_response)
        telemetry["retries_used"] = retries_used
        telemetry["evidence_retries_used"] = evidence_retries_used
        telemetry["loop_terminated"] = loop_terminated
        telemetry["loop_retry_helped"] = loop_retry_helped
        telemetry["available_tools"] = self.available_tools()
        telemetry["answer_changed_after_tool"] = (
            tool_retry_used
            and _normalize_answer_for_telemetry(answer_event.answer)
            != _normalize_answer_for_telemetry(initial_answer_text)
        )
        telemetry["verifier_supported_after_tool"] = verdict.supported if tool_retry_used else None
        return WorkflowResult(
            answer=answer_event.answer,
            citations=citations,
            trace=trace,
            telemetry=telemetry,
        )

    # -- per-stage runners (used by both initial cascade and retry loop) --

    def available_tools(self) -> list[str]:
        """Focus-pipeline tool belt for run metadata and +2/+4 diagnostics."""
        tools = ["inspect_region", "get_text_layer"]
        if self.tool_set == "full":
            tools.extend(["expand_context", "run_python"])
        if self.chart_to_table_enabled:
            tools.append("chart_to_table")
        return tools

    def _retry_budget_for_action(self, action: str) -> int:
        """Return the retry budget for a verifier action.

        `max_retries` remains the full-loop budget. Evidence-only actions get
        a bounded default budget because they only re-run expand/answer/verify
        or answer/verify; localization retries still require an explicit
        `max_retries` override.
        """
        if action not in _EVIDENCE_RETRY_ACTIONS:
            return self.max_retries
        if action == "expand_context" and self.tool_set != "full":
            return self.max_retries
        return max(self.max_retries, self.max_evidence_retries)

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
            allow_endpoint_fallback=self.allow_layout_endpoint_fallback,
            layout_max_retries=self._layout_endpoint_retries(),
            layout_timeout_s=self._layout_endpoint_timeout_s(),
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
        _add_debug_event(
            recorder,
            stage="localize",
            event_type="candidate_regions",
            retry_attempt=retry_attempt,
            payload={
                "n_regions": len(regions.candidates),
                "regions": [_region_to_debug(r) for r in regions.candidates[:50]],
            },
        )
        return regions

    async def _run_rerank(
        self,
        question_event: QuestionEvent,
        plan: PlanEvent,
        regions: RegionsEvent,
        *,
        recorder: TrajectoryRecorder,
        step_counter: _StepCounter,
        retry_attempt: int = 0,
    ) -> RegionsEvent:
        """Query-conditioned rerank — skip when no `localizer_rerank` client.

        The reranker call falls through to a no-op when `tier_router` is
        None or when `tier_router.client_for("localizer_rerank")` returns
        None, so existing tests + harnesses that don't wire the rerank
        tier still see the localizer's original ordering.
        """
        rerank_client = self._client_for("localizer_rerank")
        reranked, response = await rerank_regions(
            question_event,
            plan,
            regions,
            backend_client=rerank_client,
        )
        # Surface n_scored so traces can attribute "did the reranker run
        # and on how many regions?" without a packet body inspection.
        n_scored = sum(1 for r in reranked.candidates if r.relevance is not None)
        tier = "mid" if response is not None else "skeleton"
        action = "llm_call" if response is not None else "deterministic"
        recorder.record(
            TrajectoryStep(
                step_index=step_counter.next(),
                stage="rerank",
                tier=tier,
                action=action,
                args={
                    "n_regions": len(reranked.candidates),
                    "n_scored": n_scored,
                    "retry_attempt": retry_attempt,
                },
                obs_summary=(
                    response.text[:200] if response is not None and response.text else None
                ),
                tokens_in=(response.tokens_in if response is not None else 0),
                tokens_out=(response.tokens_out if response is not None else 0),
                latency_ms=(response.latency_ms if response is not None else 0),
                usd=(response.usd if response is not None else None),
            )
        )
        _add_debug_event(
            recorder,
            stage="rerank",
            event_type="candidate_regions",
            retry_attempt=retry_attempt,
            payload={
                "n_regions": len(reranked.candidates),
                "n_scored": n_scored,
                "regions": [_region_to_debug(r) for r in reranked.candidates[:50]],
            },
        )
        return reranked

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
        # Phase 2 of harness-growth-sprint (2026-05-11): hard-case dispatch.
        # The flag `use_react_inspector` now means "enable hard-case dispatch"
        # rather than "always use the ReAct inspector". Easy examples stay on
        # the deterministic floor; hard ones (fine-detail family,
        # highres_tiny budget, low rerank confidence) get the LLM dispatcher.
        inspector_path: str
        if self.use_react_inspector and _should_use_react_inspector(plan, regions):
            inspector_path = "react_hard_case"
        else:
            inspector_path = "deterministic"

        if inspector_path == "react_hard_case":
            from focusparse.pipeline.inspector_react import react_inspect

            inspector_client = self._client_for("inspector_dispatch")
            result = await react_inspect(
                question_event,
                plan,
                regions,
                backend_client=inspector_client,
                images_by_page=images_by_page,
                pdf_path=pdf_path,
                crop_cache_dir=self._role_cache_dir("crops"),
                text_layer_cache_dir=self._text_layer_cache_dir(),
                auto_zoom=self.auto_zoom,
                multi_scale=self.multi_scale_packets,
                chart_to_table_enabled=self.chart_to_table_enabled,
                chart_to_table_backend=self._client_for("localizer_rerank"),
            )
            evidence = result.evidence
            n_real_packets = sum(
                1 for p in evidence.packets if p.provenance.tool != "skeleton_inspector_fallback"
            )
            response = result.response
            tier = (
                "react_inspector_fallback"
                if result.fallback_used
                else ("mid" if response is not None else "deterministic")
            )
            action = "deterministic" if result.fallback_used or response is None else "llm_call"
            recorder.record(
                TrajectoryStep(
                    step_index=step_counter.next(),
                    stage="inspect",
                    tier=tier,
                    action=action,
                    tool="react_inspector",
                    args={
                        "inspector_path": inspector_path,
                        "n_packets": len(evidence.packets),
                        "n_real_packets": n_real_packets,
                        "plan_size": result.plan_size,
                        "fallback_used": result.fallback_used,
                        "chart_to_table_enabled": self.chart_to_table_enabled,
                        "retry_attempt": retry_attempt,
                    },
                    obs_summary=(response.text[:200] if response and response.text else None),
                    tokens_in=(response.tokens_in if response else 0),
                    tokens_out=(response.tokens_out if response else 0),
                    latency_ms=(response.latency_ms if response else 0),
                    usd=(response.usd if response else None),
                )
            )
            _record_packet_artifacts(recorder, evidence.packets, stage="inspect")
            _add_debug_event(
                recorder,
                stage="inspect",
                event_type="evidence_packets",
                retry_attempt=retry_attempt,
                payload={
                    "inspector_path": inspector_path,
                    "n_packets": len(evidence.packets),
                    "n_real_packets": n_real_packets,
                    "plan_size": result.plan_size,
                    "fallback_used": result.fallback_used,
                    "chart_to_table_enabled": self.chart_to_table_enabled,
                    "packets": [_packet_to_debug(p) for p in evidence.packets],
                },
            )
            return evidence

        evidence = await inspect_regions(
            question_event,
            plan,
            regions,
            images_by_page=images_by_page,
            pdf_path=pdf_path,
            crop_cache_dir=self._role_cache_dir("crops"),
            text_layer_cache_dir=self._text_layer_cache_dir(),
            auto_zoom=self.auto_zoom,
            multi_scale=self.multi_scale_packets,
            chart_to_table_enabled=self.chart_to_table_enabled,
            # Phase 7 (2026-05-11): swap the OCR-based chart extractor for
            # a vision-LLM call. localizer_rerank tier is mid (claude-haiku),
            # cheap enough at ~$0.005/chart and capable enough to read most
            # finance charts where the OCR pipeline returned empty CSV on
            # 100% of Phase 4 attempts.
            chart_to_table_backend=self._client_for("localizer_rerank"),
        )
        n_real_packets = sum(
            1 for p in evidence.packets if p.provenance.tool != "skeleton_inspector_fallback"
        )
        inspect_tier = "deterministic" if n_real_packets > 0 else "skeleton"
        recorder.record(
            TrajectoryStep(
                step_index=step_counter.next(),
                stage="inspect",
                tier=inspect_tier,
                action="tool_call",
                tool="deterministic_inspector",
                args={
                    "inspector_path": inspector_path,
                    "n_packets": len(evidence.packets),
                    "n_real_packets": n_real_packets,
                    "chart_to_table_enabled": self.chart_to_table_enabled,
                    "retry_attempt": retry_attempt,
                },
            )
        )
        _record_packet_artifacts(recorder, evidence.packets, stage="inspect")
        _add_debug_event(
            recorder,
            stage="inspect",
            event_type="evidence_packets",
            retry_attempt=retry_attempt,
            payload={
                "inspector_path": inspector_path,
                "n_packets": len(evidence.packets),
                "n_real_packets": n_real_packets,
                "chart_to_table_enabled": self.chart_to_table_enabled,
                "packets": [_packet_to_debug(p) for p in evidence.packets],
            },
        )
        return evidence

    async def _run_expand(
        self,
        evidence: EvidenceEvent,
        *,
        regions: RegionsEvent,
        pdf_path: Path | None,
        images_by_page: dict[int, Path],
        adjacency_pad: float,
        recorder: TrajectoryRecorder,
        step_counter: _StepCounter,
        retry_attempt: int = 0,
        plan: PlanEvent | None = None,
        verifier_reason: str | None = None,
        verifier_missing_context: list[str] | None = None,
        target_packet_ids: list[str] | None = None,
        retry_visual_zoom: bool = False,
    ) -> EvidenceEvent:
        # Tool-set ablation: when running with the +2-tools (minimal) belt
        # we skip expand_context entirely. The trace records a passthrough
        # step so per-stage metrics stay alignable across runs.
        if self.tool_set == "minimal":
            recorder.record(
                TrajectoryStep(
                    step_index=step_counter.next(),
                    stage="expand_context",
                    tier="skipped",
                    action="passthrough",
                    args={
                        "n_packets": len(evidence.packets),
                        "reason": "tool_set=minimal",
                        "retry_attempt": retry_attempt,
                    },
                )
            )
            _add_debug_event(
                recorder,
                stage="expand_context",
                event_type="evidence_packets",
                retry_attempt=retry_attempt,
                payload={
                    "n_packets": len(evidence.packets),
                    "reason": "tool_set=minimal",
                    "packets": [_packet_to_debug(p) for p in evidence.packets],
                },
            )
            return evidence
        expanded = await expand_context(
            evidence,
            regions=regions,
            pdf_path=pdf_path,
            images_by_page=images_by_page,
            crop_cache_dir=self._role_cache_dir("crops"),
            text_layer_cache_dir=self._text_layer_cache_dir(),
            adjacency_pad=adjacency_pad,
            use_evidence_graph=self.use_evidence_graph,
            plan=plan,
            verifier_reason=verifier_reason,
            verifier_missing_context=verifier_missing_context,
            target_packet_ids=target_packet_ids,
            retry_visual_zoom=retry_visual_zoom,
        )
        before_neighbor_counts = {p.packet_id: len(p.linked_crop_refs) for p in evidence.packets}
        before_zoom_counts = {
            p.packet_id: _packet_scale_count(p, "zoomed") for p in evidence.packets
        }
        n_with_neighbors = sum(1 for p in expanded.packets if p.linked_crop_refs)
        n_neighbors = sum(len(p.linked_crop_refs) for p in expanded.packets)
        n_neighbors_added = sum(
            max(0, len(p.linked_crop_refs) - before_neighbor_counts.get(p.packet_id, 0))
            for p in expanded.packets
        )
        n_zoomed_added = sum(
            max(0, _packet_scale_count(p, "zoomed") - before_zoom_counts.get(p.packet_id, 0))
            for p in expanded.packets
        )
        n_packets_with_new_neighbors = sum(
            len(p.linked_crop_refs) > before_neighbor_counts.get(p.packet_id, 0)
            for p in expanded.packets
        )
        expand_tier = (
            "deterministic" if (n_with_neighbors > 0 or n_zoomed_added > 0) else "skeleton"
        )
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
                    "n_neighbors_added": n_neighbors_added,
                    "n_zoomed_added": n_zoomed_added,
                    "n_packets_with_new_neighbors": n_packets_with_new_neighbors,
                    "adjacency_pad": adjacency_pad,
                    "retry_attempt": retry_attempt,
                    "verifier_reason": verifier_reason,
                    "verifier_missing_context": verifier_missing_context or [],
                    "target_packet_ids": target_packet_ids or [],
                    "visual_readability_retry": retry_visual_zoom,
                },
            )
        )
        _record_packet_artifacts(recorder, expanded.packets, stage="expand_context")
        _add_debug_event(
            recorder,
            stage="expand_context",
            event_type="evidence_packets",
            retry_attempt=retry_attempt,
            payload={
                "n_packets": len(expanded.packets),
                "n_with_neighbors": n_with_neighbors,
                "n_neighbors_attached": n_neighbors,
                "n_neighbors_added": n_neighbors_added,
                "n_zoomed_added": n_zoomed_added,
                "n_packets_with_new_neighbors": n_packets_with_new_neighbors,
                "adjacency_pad": adjacency_pad,
                "verifier_reason": verifier_reason,
                "verifier_missing_context": verifier_missing_context or [],
                "target_packet_ids": target_packet_ids or [],
                "visual_readability_retry": retry_visual_zoom,
                "packets": [_packet_to_debug(p) for p in expanded.packets],
            },
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
        evidence_scope: str = "full",
        question_family: str | None = None,
    ) -> tuple[AnswerEvent, ModelResponse]:
        answer_event, reasoner_response = await answer_from_evidence(
            question_event,
            evidence,
            backend_client=self.backend_client,
            escalation_hint=escalation_hint,
            question_family=question_family,
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
                    "evidence_scope": evidence_scope,
                },
                obs_summary=(reasoner_response.text[:200] if reasoner_response.text else None),
                tokens_in=reasoner_response.tokens_in,
                tokens_out=reasoner_response.tokens_out,
                latency_ms=reasoner_response.latency_ms,
                usd=reasoner_response.usd,
                confidence=answer_event.confidence,
            )
        )
        _add_debug_event(
            recorder,
            stage="answer",
            event_type="answer",
            retry_attempt=retry_attempt,
            payload={
                "answer": answer_event.answer,
                "citations": list(answer_event.citations),
                "confidence": answer_event.confidence,
                "had_escalation_hint": bool(escalation_hint),
                "evidence_scope": evidence_scope,
            },
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
        _add_debug_event(
            recorder,
            stage="verify",
            event_type="verdict",
            retry_attempt=retry_attempt,
            payload={
                "supported": verdict.supported,
                "reason": verdict.reason,
                "next_action": verdict.next_action,
                "confidence": verdict.confidence,
                "diagnostics": verdict.diagnostics,
            },
        )
        return verdict, verify_response


# ---------------------------------------------------------------------------
# Helpers (pure, unit-testable)
# ---------------------------------------------------------------------------


def _verifier_missing_context(verdict: VerdictEvent) -> list[str]:
    raw = verdict.diagnostics.get("missing_context")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            continue
        value = item.strip()
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _focused_retry_evidence(
    evidence: EvidenceEvent,
    target_packet_ids: list[str],
    *,
    cited_packet_ids: list[str] | None = None,
    verifier_reason: str | None = None,
) -> EvidenceEvent:
    """Restrict verifier-directed retry answers to cited/target packets.

    When the verifier names a visual/table target but the original answer also
    cited same-page explanatory text, keep a tiny amount of that context. This
    preserves verifier focus without dropping the packet that explains how to
    interpret the visual evidence.
    """
    target_set = {pid for pid in target_packet_ids if pid}
    if not target_set:
        return evidence
    target_packets = [packet for packet in evidence.packets if packet.packet_id in target_set]
    if not target_packets:
        return evidence
    supplemental_set = _focused_retry_supplemental_context_ids(
        evidence,
        target_packets=target_packets,
        target_set=target_set,
        cited_packet_ids=cited_packet_ids or [],
    )
    visual_sibling_set = _focused_retry_visual_sibling_ids(
        evidence,
        target_packets=target_packets,
        target_set=target_set,
        cited_packet_ids=cited_packet_ids or [],
        verifier_reason=verifier_reason,
    )
    keep_set = target_set | supplemental_set | visual_sibling_set
    packets = [packet for packet in evidence.packets if packet.packet_id in keep_set]
    return EvidenceEvent(packets=packets)


def _focused_retry_supplemental_context_ids(
    evidence: EvidenceEvent,
    *,
    target_packets: list[EvidencePacket],
    target_set: set[str],
    cited_packet_ids: list[str],
) -> set[str]:
    if not cited_packet_ids:
        return set()

    cited_set = {pid for pid in cited_packet_ids if pid and pid not in target_set}
    if not cited_set:
        return set()

    target_pages = {packet.page for packet in target_packets}
    out: set[str] = set()
    for packet in evidence.packets:
        if len(out) >= _MAX_FOCUSED_RETRY_SUPPLEMENTAL_PACKETS:
            break
        if packet.packet_id not in cited_set:
            continue
        if packet.page not in target_pages:
            continue
        if not _packet_is_explanatory_retry_context(packet):
            continue
        out.add(packet.packet_id)
    return out


def _packet_is_explanatory_retry_context(packet: EvidencePacket) -> bool:
    region_type = (packet.region_type or "").strip().lower()
    if region_type in _FOCUSED_RETRY_SUPPLEMENTAL_CONTEXT_TYPES:
        return True
    return bool(
        (packet.text_layer_snippet and packet.text_layer_snippet.strip())
        or (packet.ocr_snippet and packet.ocr_snippet.strip())
    )


def _focused_retry_visual_sibling_ids(
    evidence: EvidenceEvent,
    *,
    target_packets: list[EvidencePacket],
    target_set: set[str],
    cited_packet_ids: list[str],
    verifier_reason: str | None,
) -> set[str]:
    """Keep same-page visual subpanels when verifier says the target is an overview.

    Timing diagrams and oscilloscope pages often produce one large visual
    packet plus smaller same-page panel packets. If the verifier targets the
    large overview, a retry that sends only that packet can remove the precise
    panel that the reasoner needs to read gridlines or transitions.
    """
    if not verifier_reason or not _FOCUSED_RETRY_VISUAL_SIBLING_RE.search(verifier_reason):
        return set()
    visual_targets = [packet for packet in target_packets if _packet_is_visual(packet)]
    if not visual_targets:
        return set()

    cited_set = {pid for pid in cited_packet_ids if pid}
    candidates: list[tuple[int, float, float, str]] = []
    for packet in evidence.packets:
        if packet.packet_id in target_set or packet.packet_id in cited_set:
            continue
        if not _packet_is_visual(packet):
            continue
        relation = _best_visual_sibling_relation(packet, visual_targets)
        if relation is None:
            continue
        bucket, distance = relation
        candidates.append((bucket, distance, _bbox_area(packet.bbox_norm), packet.packet_id))

    candidates.sort()
    return {
        pid for _bucket, _distance, _area, pid in candidates[:_MAX_FOCUSED_RETRY_VISUAL_SIBLINGS]
    }


def _packet_is_visual(packet: EvidencePacket) -> bool:
    return (packet.region_type or "").strip().lower() in _VISUAL_PACKET_TYPES


def _best_visual_sibling_relation(
    packet: EvidencePacket,
    targets: list[EvidencePacket],
) -> tuple[int, float] | None:
    best: tuple[int, float] | None = None
    for target in targets:
        if packet.page != target.page:
            continue
        if _bbox_contains(target.bbox_norm, packet.bbox_norm, tol=0.02):
            relation = (0, _bbox_center_distance(target.bbox_norm, packet.bbox_norm))
        elif _bbox_overlap_ratio(target.bbox_norm, packet.bbox_norm) >= 0.25:
            relation = (1, _bbox_center_distance(target.bbox_norm, packet.bbox_norm))
        else:
            continue
        if best is None or relation < best:
            best = relation
    return best


def _bbox_contains(
    outer: tuple[float, float, float, float],
    inner: tuple[float, float, float, float],
    *,
    tol: float = 0.0,
) -> bool:
    return (
        inner[0] >= outer[0] - tol
        and inner[1] >= outer[1] - tol
        and inner[2] <= outer[2] + tol
        and inner[3] <= outer[3] + tol
    )


def _bbox_overlap_ratio(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0 = max(ax0, bx0)
    iy0 = max(ay0, by0)
    ix1 = min(ax1, bx1)
    iy1 = min(ay1, by1)
    if ix0 >= ix1 or iy0 >= iy1:
        return 0.0
    return ((ix1 - ix0) * (iy1 - iy0)) / max(_bbox_area(b), 1e-9)


def _bbox_area(bbox: tuple[float, float, float, float]) -> float:
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])


def _bbox_center_distance(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    acx = (a[0] + a[2]) / 2.0
    acy = (a[1] + a[3]) / 2.0
    bcx = (b[0] + b[2]) / 2.0
    bcy = (b[1] + b[3]) / 2.0
    return ((acx - bcx) ** 2 + (acy - bcy) ** 2) ** 0.5


def _evidence_scope(full_evidence: EvidenceEvent, answer_evidence: EvidenceEvent) -> str:
    if len(answer_evidence.packets) < len(full_evidence.packets):
        return "targeted"
    return "full"


def _verifier_requests_visual_readability_retry(
    verdict: VerdictEvent,
    *,
    target_packet_ids: list[str],
) -> bool:
    """True when verifier wants the same visual evidence made more readable."""
    if verdict.supported or verdict.next_action != "expand_context":
        return False
    if not target_packet_ids:
        return False
    reason = verdict.reason or ""
    return bool(_VISUAL_READABILITY_RE.search(reason) and _VISUAL_EVIDENCE_RE.search(reason))


def _verifier_target_packet_ids(
    verdict: VerdictEvent,
    *,
    valid_packet_ids: set[str] | None = None,
) -> list[str]:
    raw = verdict.diagnostics.get("target_packet_ids")
    raw_values: list[str] = []
    if isinstance(raw, str):
        raw_values.append(raw)
    elif isinstance(raw, list):
        raw_values.extend(item for item in raw if isinstance(item, str))
    raw_values.extend(_packet_id_mentions(verdict.reason))

    out: list[str] = []
    seen: set[str] = set()
    for item in raw_values:
        value = _normalize_packet_id_mention(item)
        if value is None:
            continue
        if valid_packet_ids is not None and value not in valid_packet_ids:
            continue
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _packet_scale_count(packet: EvidencePacket, scale: str) -> int:
    return sum(1 for crop in packet.multi_scale_crops if crop.scale == scale)


def _packet_id_mentions(text: str | None) -> list[str]:
    """Extract packet-id-like mentions from verifier prose."""
    if not text:
        return []
    mentions: list[str] = []
    patterns = (
        r"\bpkt[_-]?\d{1,4}\b",
        r"\bpacket\s+(?:pkt[_-]?)?\d{1,4}\b",
    )
    for pattern in patterns:
        mentions.extend(match.group(0) for match in re.finditer(pattern, text, re.IGNORECASE))
    return mentions


def _is_better_unsupported_answer(
    candidate: AnswerEvent,
    incumbent: AnswerEvent | None,
    *,
    question_text: str | None = None,
) -> bool:
    """Prefer the strongest unsupported answer if retries never get accepted.

    Verifier-directed evidence retries are useful when they produce a supported
    answer, but the n=148 branch-tip diagnostics showed several unsupported
    retries overwrote a more plausible initial answer. If the loop exhausts
    without support, keep the strongest answer the reasoner produced. A retry
    can beat a slightly higher-confidence incumbent when it is more specific to
    the question wording, which protects scorer-compliant fixes like
    `G = 24` -> `Gain = 24`.
    """
    if incumbent is None:
        return True
    if candidate.citations and not incumbent.citations:
        return True
    if incumbent.citations and not candidate.citations:
        return False
    candidate_confidence = float(candidate.confidence or 0.0)
    incumbent_confidence = float(incumbent.confidence or 0.0)
    candidate_overlap = _answer_question_overlap(candidate.answer, question_text)
    incumbent_overlap = _answer_question_overlap(incumbent.answer, question_text)
    if (
        _question_requests_single_entity(question_text)
        and _answer_looks_list_like(incumbent.answer)
        and not _answer_looks_list_like(candidate.answer)
        and candidate_confidence + _entity_retry_selection_margin(question_text)
        >= incumbent_confidence
    ):
        return True
    if (
        candidate_overlap > incumbent_overlap
        and candidate_confidence + _RETRY_SELECTION_CONFIDENCE_MARGIN >= incumbent_confidence
    ):
        return True
    if (
        incumbent_overlap > candidate_overlap
        and incumbent_confidence + _RETRY_SELECTION_CONFIDENCE_MARGIN >= candidate_confidence
    ):
        return False
    return candidate_confidence > incumbent_confidence


def _question_requests_single_entity(question_text: str | None) -> bool:
    if not question_text:
        return False
    normalized = str(question_text).lower()
    return bool(
        re.search(
            r"\bwhich\s+(?:[\w-]+\s+){0,3}"
            r"(?:country|company|entity|parameter|region|line|series|label|row|column|"
            r"value|variable)\b",
            normalized,
        )
        or re.search(
            r"\bwhich\s+\w+'s\s+",
            normalized,
        )
    )


def _entity_retry_selection_margin(question_text: str | None) -> float:
    normalized = (question_text or "").lower()
    if re.search(r"\b(?:variable|parameter|y[- ]axis|x[- ]axis)\b", normalized):
        return 0.25
    return _RETRY_SELECTION_CONFIDENCE_MARGIN


def _answer_looks_list_like(answer: str | None) -> bool:
    if not answer:
        return False
    normalized = str(answer).strip().lower()
    if ";" in normalized or "," in normalized:
        return True
    if re.search(r"\b(?:and|or)\b", normalized):
        return True
    return len(_answer_selection_tokens(normalized)) > 3


def _should_keep_best_unsupported_on_retry_abstain(
    answer: AnswerEvent | None,
    *,
    question_event: QuestionEvent,
    retries_used: int,
) -> bool:
    """Avoid erasing a cited candidate when an evidence retry gets timid.

    The verifier's first-pass `abstain` remains authoritative. This guard only
    applies after the controller already spent an evidence retry; empirically,
    those late abstentions often mean "still unsupported" rather than "the
    document proves this is unanswerable". Keep a non-abstention candidate so
    the final trace preserves the best cited answer instead of replacing it
    with an empty-citation abstention.
    """
    if retries_used <= 0 or answer is None:
        return False
    if _answer_type_is_unanswerable(question_event.answer_type):
        return False
    if not answer.citations:
        return False
    if _answer_looks_unanswerable(answer.answer):
        return False
    return float(answer.confidence or 0.0) >= _ABSTAIN_OVERRIDE_MIN_CONFIDENCE


def _should_allow_reasoner_shape_retry(
    *,
    action: str,
    answer: AnswerEvent,
    verdict: VerdictEvent,
    question_event: QuestionEvent,
    max_evidence_retries: int,
) -> bool:
    """Allow a narrow default reasoner retry for verifier-detected answer shape.

    Generic `escalate_reasoner` stays behind `max_retries`: it spends another
    frontier call without improving evidence packets. This exception is scoped
    to the common chart/table failure where the evidence is present, the
    question asks for one entity, and the answer is list-like; the verifier
    hint usually fixes that without another inspect/expand mutation.
    """
    if max_evidence_retries <= 0 or action != "escalate_reasoner":
        return False
    if verdict.supported:
        return False
    if not answer.citations:
        return False
    if not _question_requests_single_entity(question_event.question):
        return False
    if not _answer_looks_list_like(answer.answer):
        return False
    reason = verdict.reason.lower()
    return bool(
        "single" in reason
        or "one " in reason
        or "two " in reason
        or "multiple" in reason
        or "does not quantify" in reason
        or "did not answer" in reason
        or "actual question" in reason
        or "which variable" in reason
        or "y-axis variable" in reason
        or "y axis variable" in reason
    )


def _answer_type_is_unanswerable(answer_type: str | None) -> bool:
    if not answer_type:
        return False
    stem = str(answer_type).split(".")[-1].lower()
    return stem == "unanswerable"


def _answer_looks_unanswerable(answer: str | None) -> bool:
    if not answer:
        return True
    normalized = str(answer).strip().lower()
    return normalized in {"unanswerable", "unknown", "cannot determine", "can't determine"}


def _answer_question_overlap(answer: str | None, question_text: str | None) -> int:
    if not answer or not question_text:
        return 0
    q_tokens = _answer_selection_tokens(question_text)
    if not q_tokens:
        return 0
    return len(q_tokens & _answer_selection_tokens(answer))


def _answer_selection_tokens(text: str) -> set[str]:
    normalized = str(text).lower()
    normalized = normalized.replace("µ", "u")
    return {
        token
        for token in _ANSWER_TOKEN_RE.findall(normalized)
        if len(token) > 1 and token not in _ANSWER_SELECTION_STOPWORDS
    }


def _normalize_packet_id_mention(value: str) -> str | None:
    normalized = value.strip().lower()
    if not normalized:
        return None
    match = re.fullmatch(r"pkt[_-]?(\d{1,4})", normalized)
    if match:
        return f"pkt_{int(match.group(1)):03d}"
    match = re.fullmatch(r"packet\s+(?:pkt[_-]?)?(\d{1,4})", normalized)
    if match:
        return f"pkt_{int(match.group(1)):03d}"
    match = re.fullmatch(r"\d{1,4}", normalized)
    if match:
        return f"pkt_{int(match.group(0)):03d}"
    if re.fullmatch(r"[a-z][a-z0-9_-]{0,79}", normalized):
        return normalized
    return None


def _plan_with_extra_evidence_types(plan: PlanEvent, extra_types: list[str]) -> PlanEvent:
    if not extra_types:
        return plan
    evidence_types: list[str] = []
    seen: set[str] = set()
    for raw in [*plan.evidence_types, *extra_types]:
        value = (raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        evidence_types.append(value)
    if evidence_types == plan.evidence_types:
        return plan
    return plan.model_copy(update={"evidence_types": evidence_types})


def _add_debug_event(
    recorder: TrajectoryRecorder,
    *,
    stage: str,
    event_type: str,
    payload: dict[str, Any],
    retry_attempt: int = 0,
    step_index: int | None = None,
) -> None:
    """Record one compact viewer/debug event."""
    recorder.add_debug_event(
        event_id=recorder.next_debug_event_id(stage, event_type),
        stage=stage,
        event_type=event_type,
        step_index=step_index,
        retry_attempt=retry_attempt,
        payload=payload,
    )


def _record_page_artifacts(recorder: TrajectoryRecorder, images_by_page: dict[int, Path]) -> None:
    for page, path in sorted(images_by_page.items()):
        recorder.add_artifact(
            artifact_id=f"page:{page}",
            kind="page_image",
            path=str(path),
            page=page,
            label=f"page {page}",
        )


def _record_packet_artifacts(
    recorder: TrajectoryRecorder,
    packets: list[EvidencePacket],
    *,
    stage: str,
) -> None:
    for packet in packets:
        _record_ref_artifact(
            recorder,
            kind="thumbnail",
            ref=packet.page_thumbnail_ref,
            page=packet.page,
            bbox_norm=packet.bbox_norm,
            packet_id=packet.packet_id,
            stage=stage,
            label=f"{packet.packet_id} page thumbnail",
        )
        _record_ref_artifact(
            recorder,
            kind="crop",
            ref=packet.local_crop_ref,
            page=packet.page,
            bbox_norm=packet.bbox_norm,
            packet_id=packet.packet_id,
            stage=stage,
            label=f"{packet.packet_id} tight crop",
        )
        if packet.context_crop_ref:
            _record_ref_artifact(
                recorder,
                kind="crop",
                ref=packet.context_crop_ref,
                page=packet.page,
                bbox_norm=packet.bbox_norm,
                packet_id=packet.packet_id,
                stage=stage,
                label=f"{packet.packet_id} context crop",
            )
        for i, crop in enumerate(packet.multi_scale_crops):
            _record_ref_artifact(
                recorder,
                kind="crop",
                ref=crop.ref,
                page=packet.page,
                bbox_norm=crop.bbox_norm,
                packet_id=packet.packet_id,
                stage=stage,
                label=f"{packet.packet_id} {crop.scale} crop",
                meta={"scale": crop.scale, "index": i},
            )
        for i, ref in enumerate(packet.linked_crop_refs):
            neighbor_type = (
                packet.linked_neighbor_types[i]
                if i < len(packet.linked_neighbor_types)
                else "linked"
            )
            _record_ref_artifact(
                recorder,
                kind="crop",
                ref=ref,
                page=packet.page,
                packet_id=packet.packet_id,
                stage=stage,
                label=f"{packet.packet_id} {neighbor_type}",
                meta={"neighbor_type": neighbor_type, "index": i},
            )
        if packet.chart_csv:
            recorder.add_artifact(
                artifact_id=f"chart_csv:{packet.packet_id}:{stage}",
                kind="chart_csv",
                ref=packet.packet_id,
                page=packet.page,
                bbox_norm=packet.bbox_norm,
                packet_id=packet.packet_id,
                stage=stage,
                label=f"{packet.packet_id} chart CSV",
                meta={"confidence": packet.chart_extraction_confidence},
            )


def _record_ref_artifact(
    recorder: TrajectoryRecorder,
    *,
    kind: str,
    ref: str | None,
    page: int | None,
    bbox_norm: tuple[float, float, float, float] | None = None,
    packet_id: str | None = None,
    stage: str | None = None,
    label: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    if not ref:
        return
    recorder.add_artifact(
        artifact_id=f"{kind}:{packet_id or page or 'unknown'}:{Path(str(ref)).name}:{stage or ''}",
        kind=kind,
        path=str(ref) if Path(str(ref)).is_absolute() else None,
        ref=str(ref),
        page=page,
        bbox_norm=bbox_norm,
        packet_id=packet_id,
        stage=stage,
        label=label,
        meta=meta or {},
    )


def _page_candidate_to_debug(pc: Any) -> dict[str, Any]:
    return {
        "page": pc.page,
        "score": pc.score,
        "reason_code": pc.reason_code,
    }


def _region_to_debug(region: Any) -> dict[str, Any]:
    return {
        "region_id": region.region_id,
        "page": region.page,
        "bbox_norm": list(region.bbox_norm),
        "region_type": region.region_type,
        "score": region.score,
        "supporting_signals": list(region.supporting_signals),
        "expansion_hints": list(region.expansion_hints),
        "relevance": region.relevance,
        "needed_for": region.needed_for,
    }


def _packet_to_debug(packet: EvidencePacket) -> dict[str, Any]:
    return {
        "packet_id": packet.packet_id,
        "page": packet.page,
        "bbox_norm": list(packet.bbox_norm),
        "region_type": packet.region_type,
        "local_crop_ref": packet.local_crop_ref,
        "linked_crop_refs": list(packet.linked_crop_refs),
        "linked_neighbor_types": list(packet.linked_neighbor_types),
        "multi_scale_crops": [
            {"ref": c.ref, "bbox_norm": list(c.bbox_norm), "scale": c.scale}
            for c in packet.multi_scale_crops
        ],
        "text_layer_snippet": packet.text_layer_snippet,
        "ocr_snippet": packet.ocr_snippet,
        "chart_csv": packet.chart_csv,
        "chart_extraction_confidence": packet.chart_extraction_confidence,
        "confidence": packet.confidence,
        "provenance_tool": packet.provenance.tool if packet.provenance else None,
        "provenance_mode": packet.provenance.mode if packet.provenance else None,
        "provenance_args_hash": packet.provenance.args_hash if packet.provenance else None,
    }


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


def _packet_to_summary(p: EvidencePacket) -> EvidencePacketSummary:
    """JSON-safe view of a packet for the trace evidence_snapshot."""
    return EvidencePacketSummary(
        packet_id=p.packet_id,
        page=p.page,
        bbox_norm=p.bbox_norm,
        region_type=p.region_type,
        local_crop_ref=p.local_crop_ref,
        linked_crop_refs=list(p.linked_crop_refs),
        linked_neighbor_types=list(p.linked_neighbor_types),
        multi_scale_crops=[c.model_dump(mode="json") for c in p.multi_scale_crops],
        text_layer_snippet=p.text_layer_snippet,
        ocr_snippet=p.ocr_snippet,
        chart_csv=p.chart_csv,
        chart_extraction_confidence=p.chart_extraction_confidence,
        confidence=p.confidence,
        provenance_tool=p.provenance.tool if p.provenance else None,
    )


def _make_telemetry(response: ModelResponse) -> dict[str, Any]:
    return {
        "tokens_in": response.tokens_in,
        "tokens_out": response.tokens_out,
        "usd": response.usd,
        "latency_ms": response.latency_ms,
        "raw_response_len": len(response.text or ""),
    }


def _normalize_answer_for_telemetry(answer: str) -> str:
    """Low-stakes normalization for answer-change instrumentation."""
    return " ".join(str(answer or "").strip().lower().split())


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


def _format_hint(answer_type: object) -> str:
    """Type-aware answer-format hint appended to the user prompt.

    Lets a single-shot VLM emit the strict form the scorer expects (a bare
    number / label / yes-no / letter) instead of prose like "About 50% of
    the way down the displayed memory stack." Empty string for unknown
    types so we never pollute the prompt with junk.
    """
    s = str(answer_type)
    stem = s.split(".")[-1].lower() if "." in s else s.lower()
    if stem == "numeric":
        return (
            "Answer with a single number, including the requested unit or % sign "
            "when the question explicitly asks for one. Do not add explanations "
            "or extra units beyond what the question asks for."
        )
    if stem == "exact_match":
        return (
            "Answer with the exact label, identifier, or phrase from the document. "
            "Quote the document verbatim — do not paraphrase, abbreviate, or add "
            "explanation text that isn't present in the document. Match the "
            "document's exact punctuation. Even if the question asks for an "
            "explanation, put only the final exact answer in the answer field. "
            "For register bit-field assignments, omit spaces around '=' and "
            "separate assignments with comma+space, e.g. [15:14]=b00, [8:5]=b1111."
        )
    if stem == "boolean":
        return "Answer 'yes' or 'no'."
    if stem == "multiple_choice":
        return "Answer with the letter of the correct choice (A, B, C, ...)."
    if stem == "unanswerable":
        return "If the document does not contain the answer, reply 'Unanswerable'."
    return ""


def _build_simple_user_prompt(
    example: BenchmarkExample,
    image_pages: list[int] | None,
) -> str:
    """Compose the user-side prompt: question + page mapping + format hint.

    `image_pages` enumerates which source PDF page each image corresponds
    to so the model emits citations against real page numbers (not 1-indexed
    positional). Tiled protocols pass the constituent pages of the tile.
    """
    lines = [f"Question: {example.question}"]
    if image_pages:
        if len(image_pages) == 1:
            lines.append(f"This image is from page {image_pages[0]} of the document.")
        else:
            listing = ", ".join(f"image {i + 1} = page {p}" for i, p in enumerate(image_pages))
            lines.append(f"Images correspond to: {listing}")
        lines.append("Cite source page numbers from this list, not positional indices.")
    hint = _format_hint(example.answer_type)
    if hint:
        lines.append(hint)
    return "\n".join(lines)


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
        *,
        image_pages: list[int] | None = None,
    ) -> WorkflowResult:
        recorder = TrajectoryRecorder(example_id=example.id, question=example.question)
        recorder.set_plan({"agent": "simple", "protocol": self.protocol, "n_images": len(images)})

        prompt = _build_simple_user_prompt(example, image_pages)
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
