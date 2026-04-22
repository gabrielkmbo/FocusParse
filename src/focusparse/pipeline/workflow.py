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
    QuestionEvent,
)
from focusparse.pipeline.expander import expand_context
from focusparse.pipeline.inspector import inspect_regions
from focusparse.pipeline.localizer import propose_regions
from focusparse.pipeline.planner import plan_question
from focusparse.pipeline.reasoner import answer_from_evidence
from focusparse.pipeline.router import route_pages
from focusparse.pipeline.verifier import verify_answer
from focusparse.traces.recorder import RunTrace, TrajectoryRecorder, TrajectoryStep

if TYPE_CHECKING:
    from focusparse._parser_bench import BenchmarkExample


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
    ) -> None:
        self.backend_client = backend_client
        self.config = config
        self.tier_router = tier_router
        self.cache = cache
        self.tools = tools

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

    async def run(
        self,
        example: BenchmarkExample,
        images: list[Path],
        *,
        protocol: str = "focus",
        output_dir: Path | None = None,
    ) -> WorkflowResult:
        del output_dir  # unused in skeleton
        recorder = TrajectoryRecorder(example_id=example.id, question=example.question)
        recorder.set_plan({"agent": "focus", "protocol": protocol, "n_images": len(images)})

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
                step_index=0,
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

        # --- ROUTE_PAGES ---------------------------------------------------
        pages = await route_pages(
            question_event,
            plan,
            pages=sorted(images_by_page.keys()),
        )
        recorder.record(
            TrajectoryStep(
                step_index=1,
                stage="route_pages",
                tier="skeleton",
                action="deterministic",
                args={"candidates": [pc.page for pc in pages.candidates]},
            )
        )

        # --- PROPOSE_REGIONS ----------------------------------------------
        regions = await propose_regions(question_event, plan, pages)
        recorder.record(
            TrajectoryStep(
                step_index=2,
                stage="localize",
                tier="skeleton",
                action="deterministic",
                args={"n_regions": len(regions.candidates)},
            )
        )

        # --- INSPECT -------------------------------------------------------
        evidence = await inspect_regions(
            question_event,
            plan,
            regions,
            images_by_page=images_by_page,
        )
        recorder.record(
            TrajectoryStep(
                step_index=3,
                stage="inspect",
                tier="skeleton",
                action="tool_call",
                tool="skeleton_inspector",
                args={"n_packets": len(evidence.packets)},
            )
        )

        # --- EXPAND_CONTEXT -----------------------------------------------
        evidence = await expand_context(evidence)
        recorder.record(
            TrajectoryStep(
                step_index=4,
                stage="expand_context",
                tier="skeleton",
                action="deterministic",
                args={"n_packets": len(evidence.packets)},
            )
        )

        # --- ANSWER --------------------------------------------------------
        answer_event, reasoner_response = await answer_from_evidence(
            question_event,
            evidence,
            backend_client=self.backend_client,
        )
        recorder.record(
            TrajectoryStep(
                step_index=5,
                stage="answer",
                tier="reasoner",
                action="llm_call",
                args={"n_packets": len(evidence.packets)},
                obs_summary=(reasoner_response.text[:200] if reasoner_response.text else None),
                tokens_in=reasoner_response.tokens_in,
                tokens_out=reasoner_response.tokens_out,
                latency_ms=reasoner_response.latency_ms,
                usd=reasoner_response.usd,
                confidence=answer_event.confidence,
            )
        )

        # --- VERIFY --------------------------------------------------------
        verifier_client = self._client_for("verifier")
        verdict, verify_response = await verify_answer(
            question_event,
            evidence,
            answer_event,
            backend_client=verifier_client,
        )
        recorder.record(
            TrajectoryStep(
                step_index=6,
                stage="verify",
                tier=("mid" if verify_response is not None else "skeleton"),
                action=("llm_call" if verify_response is not None else "deterministic"),
                args={
                    "next_action": verdict.next_action,
                    "supported": verdict.supported,
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

        # Convert packet-id citations back to {page, bbox} dicts.
        citations = _citations_from_packets(answer_event.citations, evidence.packets)
        trace = recorder.finalize(answer=answer_event.answer, citations=citations)

        telemetry = _make_telemetry(reasoner_response)
        return WorkflowResult(
            answer=answer_event.answer,
            citations=citations,
            trace=trace,
            telemetry=telemetry,
        )


# ---------------------------------------------------------------------------
# Helpers (pure, unit-testable)
# ---------------------------------------------------------------------------


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
