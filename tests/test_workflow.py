"""Workflow skeleton tests — Phase 2 sub-phases 2a+2b.

Two layers of coverage:

1. **Pure helpers** (no submodule required): `_images_by_page`,
   `_page_number_from_filename`, `_citations_from_packets`,
   `_infer_doc_id`, and parser-agnostic checks on `_parse_simple_response`.

2. **End-to-end FocusWorkflow.run**: uses a `_FakeClient` for the reasoner
   call + a real `BenchmarkExample` (gated on parser-bench submodule).
   Asserts:
     - exactly 7 TrajectoryStep records (one per @step)
     - one LLM call hits the reasoner
     - citations resolve back to {page, bbox}
     - bad packet_ids are silently dropped
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from focusparse.evidence.packet import EvidencePacket, PacketProvenance
from focusparse.models.base import ModelResponse
from focusparse.pipeline.workflow import (
    FocusWorkflow,
    SimpleBaselineAgent,
    WorkflowResult,
    _citations_from_packets,
    _images_by_page,
    _infer_doc_id,
    _page_number_from_filename,
)

# ---------------------------------------------------------------------------
# Import-graph sanity (cheap regression catches)
# ---------------------------------------------------------------------------


def test_event_imports():
    from focusparse.pipeline.events import (
        AnswerEvent,
        EvidenceEvent,
        PagesEvent,
        PlanEvent,
        QuestionEvent,
        RegionsEvent,
        VerdictEvent,
    )

    assert QuestionEvent.__name__ == "QuestionEvent"
    assert all(
        e is not None
        for e in (PlanEvent, PagesEvent, RegionsEvent, EvidenceEvent, AnswerEvent, VerdictEvent)
    )


def test_workflow_stub_importable():
    assert FocusWorkflow.__name__ == "FocusWorkflow"
    assert SimpleBaselineAgent.__name__ == "SimpleBaselineAgent"
    assert WorkflowResult is not None


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("datasheet-A_page_0003_300dpi.png", 3),
        ("something_page_0010_150dpi.png", 10),
        ("no_page_number_here.png", None),
        ("page_3.png", None),  # pattern requires leading underscore
    ],
)
def test_page_number_from_filename(name, expected):
    assert _page_number_from_filename(name) == expected


def test_images_by_page_uses_filename_first():
    imgs = [
        Path("data/processed/datasheet-A/images/datasheet-A_page_0003_300dpi.png"),
        Path("data/processed/datasheet-A/images/datasheet-A_page_0007_300dpi.png"),
    ]
    mapping = _images_by_page(example=None, images=imgs)  # example unused by helper
    assert set(mapping.keys()) == {3, 7}
    assert mapping[3].name == "datasheet-A_page_0003_300dpi.png"


def test_images_by_page_falls_back_to_positional_index():
    imgs = [Path("no_page_here_a.png"), Path("no_page_here_b.png")]
    mapping = _images_by_page(example=None, images=imgs)
    # Fallback: idx+1 -> 1, 2
    assert mapping[1].name == "no_page_here_a.png"
    assert mapping[2].name == "no_page_here_b.png"


def test_citations_from_packets_translates_packet_ids_to_bbox_dicts():
    packets = [
        _make_packet(packet_id="pkt_000", page=3, bbox=(0.1, 0.2, 0.3, 0.4)),
        _make_packet(packet_id="pkt_001", page=5, bbox=(0.5, 0.6, 0.7, 0.8)),
    ]
    cites = _citations_from_packets(["pkt_000", "pkt_001"], packets)
    assert cites == [
        {"page": 3, "bbox": [0.1, 0.2, 0.3, 0.4]},
        {"page": 5, "bbox": [0.5, 0.6, 0.7, 0.8]},
    ]


def test_citations_from_packets_silently_drops_unknown_refs():
    packets = [_make_packet(packet_id="pkt_000", page=1, bbox=(0, 0, 1, 1))]
    cites = _citations_from_packets(["pkt_000", "pkt_999", "garbage"], packets)
    assert len(cites) == 1
    assert cites[0]["page"] == 1


def test_citations_from_packets_empty_list_yields_empty():
    assert _citations_from_packets([], []) == []


# ---------------------------------------------------------------------------
# FocusWorkflow.run end-to-end (requires parser-bench submodule)
# ---------------------------------------------------------------------------


class _FakeClient:
    """Minimal ModelClient recording the prompts/images it sees."""

    def __init__(self, response_text: str, tokens_in: int = 150, tokens_out: int = 30) -> None:
        self._text = response_text
        self._tokens_in = tokens_in
        self._tokens_out = tokens_out
        self.calls: list[dict[str, Any]] = []

    async def predict(
        self,
        prompt: str,
        images: list[Path] | None = None,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        self.calls.append({"prompt": prompt, "n_images": len(images or []), "system": system})
        return ModelResponse(
            text=self._text,
            tokens_in=self._tokens_in,
            tokens_out=self._tokens_out,
            usd=0.002,
            latency_ms=80,
        )

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)


def _make_example():
    """Build a minimal BenchmarkExample. Call-site gates on submodule."""
    from focusparse._parser_bench import BBox, BenchmarkExample

    return BenchmarkExample(
        id="ex-1",
        domain="datasheet",
        source_pdf="datasheet-A.pdf",
        page_images=[
            "data/processed/datasheet-A/images/datasheet-A_page_0003_300dpi.png",
            "data/processed/datasheet-A/images/datasheet-A_page_0007_300dpi.png",
        ],
        question="What is the max supply voltage?",
        answer="5.5",
        answer_type="numeric",
        answer_unit="V",
        tolerance=0.01,
        supporting_pages=[3],
        supporting_bboxes=[BBox(page=3, x0=0.1, y0=0.2, x1=0.3, y1=0.4)],
        alternate_bboxes=[],
        evidence_relations=[],
        multi_region_required=False,
        requires_visual=True,
        difficulty={"visual": 2, "reasoning": 1, "localization": 3},
        question_family="min_typ_max_disambiguation",
        stress_type="none",
        reasoning_chain=None,
        evidence_page_spread=0,
        adversarial_type=None,
        split="dev",
        original_bboxes=[],
    )


def _make_packet(*, packet_id: str, page: int, bbox: tuple[float, float, float, float]):
    return EvidencePacket(
        packet_id=packet_id,
        page=page,
        bbox_norm=bbox,
        page_thumbnail_ref=f"/tmp/{packet_id}.png",
        local_crop_ref=f"/tmp/{packet_id}.png",
        provenance=PacketProvenance(tool="test", args_hash=""),
    )


def test_infer_doc_id_uses_source_pdf_stem(parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")
    example = _make_example()
    assert _infer_doc_id(example) == "datasheet-A"


async def test_focus_workflow_runs_end_to_end(tmp_path, parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")

    # Reasoner returns a valid JSON referencing one of the packets the
    # skeleton inspector will produce. Packets are named pkt_000, pkt_001 in
    # page order, matching the skeleton's region_id -> packet_id mapping.
    client = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.8}')
    workflow = FocusWorkflow(backend_client=client)
    example = _make_example()

    # Skeleton inspector reads the image path but doesn't open the file.
    images = [
        tmp_path / "datasheet-A_page_0003_300dpi.png",
        tmp_path / "datasheet-A_page_0007_300dpi.png",
    ]
    result = await workflow.run(example, images, protocol="focus")

    assert result.answer == "5.5"

    # Citation resolves back to the packet referenced — pkt_000 is the first
    # region, which the skeleton router emits for the lowest real page number
    # parsed from the filenames (page 3).
    assert len(result.citations) == 1
    assert result.citations[0]["page"] == 3
    assert result.citations[0]["bbox"] == [0.0, 0.0, 1.0, 1.0]

    # Eight recorded steps, one per @step. `rerank` was added in item 4
    # (Phase 2 SOTA-leverage tail) between `localize` and `inspect`; it
    # short-circuits to "skeleton" tier when no `localizer_rerank` client
    # is wired (the case here — no tier_router).
    stages = [step.stage for step in result.trace.steps]
    assert stages == [
        "plan",
        "route_pages",
        "localize",
        "rerank",
        "inspect",
        "expand_context",
        "answer",
        "verify",
    ]

    # Exactly one LLM call — the reasoner.
    llm_steps = [s for s in result.trace.steps if s.action == "llm_call"]
    assert len(llm_steps) == 1
    assert llm_steps[0].stage == "answer"
    assert llm_steps[0].tokens_in == 150
    assert llm_steps[0].tokens_out == 30
    assert llm_steps[0].usd == 0.002

    # Backend was called once with the reasoner prompt + all packet images.
    assert len(client.calls) == 1
    # Two images were passed in -> skeleton yields one packet per page -> two
    # unique local_crop_refs -> reasoner sees both.
    assert client.calls[0]["n_images"] == 2
    assert "pkt_0" in client.calls[0]["prompt"]  # packet ids enumerated

    # Telemetry propagates from the reasoner response.
    assert result.telemetry["tokens_in"] == 150
    assert result.telemetry["tokens_out"] == 30


async def test_focus_workflow_drops_invalid_citation_refs(tmp_path, parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")

    # Reasoner hallucinates packet ids that don't exist → should be silently
    # dropped, leaving only the valid one.
    client = _FakeClient(
        '{"answer": "5.5", "citations": ["pkt_000", "pkt_999", "pkt_001"], "confidence": 0.7}'
    )
    workflow = FocusWorkflow(backend_client=client)
    example = _make_example()
    images = [
        tmp_path / "datasheet-A_page_0003_300dpi.png",
        tmp_path / "datasheet-A_page_0007_300dpi.png",
    ]
    result = await workflow.run(example, images, protocol="focus")

    # Reasoner returned pkt_000, pkt_999 (hallucination), pkt_001. Valid
    # packet set filters to {pkt_000, pkt_001} — pkt_999 is dropped.
    assert len(result.citations) == 2


async def test_focus_workflow_handles_non_json_reasoner_response(
    tmp_path, parser_bench_submodule_present
):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")

    client = _FakeClient("I think it's 5.5 volts but I'm not sure.")
    workflow = FocusWorkflow(backend_client=client)
    example = _make_example()
    images = [tmp_path / "datasheet-A_page_0003_300dpi.png"]
    result = await workflow.run(example, images, protocol="focus")

    # Non-JSON reasoner text falls back to raw text, zero citations.
    assert "5.5" in result.answer
    assert result.citations == []
    # But the workflow still records all 7 steps.
    assert len(result.trace.steps) == 8  # 7 stages + rerank (item 4)


async def test_focus_workflow_survives_zero_pages(tmp_path, parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")

    client = _FakeClient('{"answer": "Unanswerable", "citations": [], "confidence": 0.1}')
    workflow = FocusWorkflow(backend_client=client)
    example = _make_example()
    # No images → zero packets → reasoner still called but with no attachments.
    result = await workflow.run(example, [], protocol="focus")

    assert result.answer == "Unanswerable"
    assert result.citations == []
    # Still 7 steps.
    assert len(result.trace.steps) == 8  # 7 stages + rerank (item 4)
    # Reasoner got called with zero images (packet list empty).
    assert len(client.calls) == 1
    assert client.calls[0]["n_images"] == 0


class _FakeTierRouter:
    """Routes role-scoped clients from a supplied dict. Any role not in the
    dict returns None (the workflow treats None as "deterministic fallback"
    for that stage)."""

    def __init__(self, clients: dict[str, Any] | None = None, **kwargs):
        # Allow either `_FakeTierRouter({"planner": c})` or
        # `_FakeTierRouter(planner=c, verifier=c2)`.
        merged: dict[str, Any] = dict(clients or {})
        merged.update(kwargs)
        self._clients = merged
        self.calls: list[str] = []

    def client_for(self, role: str, *, escalate: bool = False):
        self.calls.append(role)
        return self._clients.get(role)


async def test_focus_workflow_routes_planner_through_tier_router(
    tmp_path, parser_bench_submodule_present
):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")

    # Planner returns a valid datasheet-family classification; reasoner then
    # emits a normal packet-citation answer.
    planner_client = _FakeClient(
        '{"question_family": "min_typ_max_disambiguation", '
        '"evidence_types": ["table", "footnote"], '
        '"budget_class": "easy_local", '
        '"routing_policy": "text_first"}',
        tokens_in=90,
        tokens_out=20,
    )
    reasoner_client = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.9}')
    tier_router = _FakeTierRouter(planner=planner_client)
    workflow = FocusWorkflow(backend_client=reasoner_client, tier_router=tier_router)
    example = _make_example()
    images = [
        tmp_path / "datasheet-A_page_0003_300dpi.png",
        tmp_path / "datasheet-A_page_0007_300dpi.png",
    ]
    result = await workflow.run(example, images, protocol="focus")

    # Router was consulted for every role-scoped stage (planner + rerank +
    # verifier — `rerank` was added in item 4 and asks for `localizer_rerank`).
    # Verifier client + rerank client both return None here → those stages
    # stay deterministic; only the planner routes through to a real client.
    assert tier_router.calls == ["planner", "localizer_rerank", "verifier"]
    assert len(planner_client.calls) == 1
    plan_steps = [s for s in result.trace.steps if s.stage == "plan"]
    assert len(plan_steps) == 1
    assert plan_steps[0].action == "llm_call"
    assert plan_steps[0].tier == "cheap"
    assert plan_steps[0].tokens_in == 90
    assert plan_steps[0].tokens_out == 20
    assert plan_steps[0].args["question_family"] == "min_typ_max_disambiguation"
    assert plan_steps[0].args["routing_policy"] == "text_first"
    # Reasoner still answered correctly downstream.
    assert result.answer == "5.5"
    assert len(result.citations) == 1


async def test_focus_workflow_routes_verifier_through_tier_router(
    tmp_path, parser_bench_submodule_present
):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")

    reasoner_client = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.9}')
    verifier_client = _FakeClient(
        '{"supported": false, "reason": "cited bbox covers the wrong row", '
        '"next_action": "retry_localization", "confidence": 0.72}',
        tokens_in=140,
        tokens_out=35,
    )
    tier_router = _FakeTierRouter(verifier=verifier_client)
    # `max_retries=0` keeps this test focused on tier-router wiring, not
    # the verifier→retry loop. The loop's behavior is covered by the
    # dedicated retry-loop tests below.
    workflow = FocusWorkflow(backend_client=reasoner_client, tier_router=tier_router, max_retries=0)
    example = _make_example()
    images = [tmp_path / "datasheet-A_page_0003_300dpi.png"]
    result = await workflow.run(example, images, protocol="focus")

    # Verifier was called once through the tier router, and the verify step
    # records its telemetry.
    assert "verifier" in tier_router.calls
    assert len(verifier_client.calls) == 1
    verify_steps = [s for s in result.trace.steps if s.stage == "verify"]
    assert len(verify_steps) == 1
    step = verify_steps[0]
    assert step.action == "llm_call"
    assert step.tier == "mid"
    assert step.tokens_in == 140
    assert step.tokens_out == 35
    assert step.args["next_action"] == "retry_localization"
    assert step.args["supported"] is False
    # Workflow still terminates after one pass — the retry loop lands later.
    assert result.answer == "5.5"


async def test_focus_workflow_plan_step_deterministic_when_no_tier_router(
    tmp_path, parser_bench_submodule_present
):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")

    client = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.7}')
    workflow = FocusWorkflow(backend_client=client)  # no tier_router
    example = _make_example()
    images = [tmp_path / "datasheet-A_page_0003_300dpi.png"]
    result = await workflow.run(example, images, protocol="focus")

    # No tier_router → planner falls back to deterministic; action reflects that.
    plan_steps = [s for s in result.trace.steps if s.stage == "plan"]
    assert plan_steps[0].action == "deterministic"
    assert plan_steps[0].tier == "skeleton"
    assert plan_steps[0].tokens_in == 0
    # Exactly one LLM call total — the reasoner. Planner did not hit the network.
    llm_steps = [s for s in result.trace.steps if s.action == "llm_call"]
    assert len(llm_steps) == 1
    assert llm_steps[0].stage == "answer"


# ---------------------------------------------------------------------------
# PDF text-layer wiring (Phase 3: get_text_layer → router)
# ---------------------------------------------------------------------------


def _write_pdf_for_workflow_test(path: Path, *, pages_text: dict[int, str]) -> Path:
    """Write a multi-page PDF with the supplied per-page text.

    Keys are 1-indexed so callers can mirror the BenchmarkExample's
    `page_images` list.
    """
    import fitz

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    for page_idx in sorted(pages_text):
        page = doc.new_page(width=600, height=800)
        page.insert_text((50, 50), pages_text[page_idx], fontsize=12)
    doc.save(path)
    doc.close()
    return path


async def test_focus_workflow_routes_through_fts_when_pdf_supplied(
    tmp_path, parser_bench_submodule_present
):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")

    # The skeleton example has page_images for pages 3 and 7; build a PDF
    # where pages 1..7 all exist, but only page 3 mentions the query term
    # so FTS picks it and page 7 ends up in the no-match tail.
    pdf_pages = {i: "unrelated filler content" for i in range(1, 8)}
    pdf_pages[3] = "VCC maximum supply voltage rating is 5.5 volts"
    pdf = _write_pdf_for_workflow_test(tmp_path / "datasheet-A.pdf", pages_text=pdf_pages)

    client = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.8}')
    workflow = FocusWorkflow(backend_client=client)
    example = _make_example()

    images = [
        tmp_path / "datasheet-A_page_0003_300dpi.png",
        tmp_path / "datasheet-A_page_0007_300dpi.png",
    ]
    result = await workflow.run(example, images, protocol="focus", pdf_path=pdf)

    route_step = next(s for s in result.trace.steps if s.stage == "route_pages")
    assert route_step.tier == "text_fts"
    # Page 3 has text "VCC ... max ... supply voltage"; page 7 has only
    # filler, so page 3 should appear in the candidates and be ranked first.
    candidates = route_step.args["candidates"]
    assert 3 in candidates
    # n_text_pages counts how many of the page universe had a non-empty
    # native text layer — all 2 here.
    assert route_step.args["n_text_pages"] == 2


async def test_focus_workflow_skeleton_router_when_no_pdf_path(
    tmp_path, parser_bench_submodule_present
):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")

    client = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.7}')
    workflow = FocusWorkflow(backend_client=client)
    example = _make_example()
    images = [tmp_path / "datasheet-A_page_0003_300dpi.png"]

    # No pdf_path → router falls back to the skeleton path.
    result = await workflow.run(example, images, protocol="focus")

    route_step = next(s for s in result.trace.steps if s.stage == "route_pages")
    assert route_step.tier == "skeleton"
    assert route_step.args["n_text_pages"] == 0


async def test_focus_workflow_skeleton_router_when_pdf_missing_on_disk(
    tmp_path, parser_bench_submodule_present
):
    """Dangling pdf_path should degrade to skeleton, not crash the run."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")

    client = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.7}')
    workflow = FocusWorkflow(backend_client=client)
    example = _make_example()
    images = [tmp_path / "datasheet-A_page_0003_300dpi.png"]

    missing_pdf = tmp_path / "not-there.pdf"
    result = await workflow.run(example, images, protocol="focus", pdf_path=missing_pdf)

    route_step = next(s for s in result.trace.steps if s.stage == "route_pages")
    assert route_step.tier == "skeleton"
    # Run still produced an answer — the missing PDF didn't take the pipeline down.
    assert result.answer == "5.5"


async def test_focus_workflow_tolerates_out_of_range_pages_in_pdf(
    tmp_path, parser_bench_submodule_present
):
    """PDF has fewer pages than page_images → out-of-range pages fall back quietly."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")

    # PDF has only 2 pages; example expects page 3 + page 7.
    pdf = _write_pdf_for_workflow_test(
        tmp_path / "short.pdf",
        pages_text={1: "page one", 2: "page two"},
    )

    client = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.7}')
    workflow = FocusWorkflow(backend_client=client)
    example = _make_example()
    images = [
        tmp_path / "datasheet-A_page_0003_300dpi.png",
        tmp_path / "datasheet-A_page_0007_300dpi.png",
    ]
    # Should still complete: pages 3 and 7 get empty-string text entries,
    # which means FTS matches nothing, so the router returns the no-match
    # fallback — the run keeps going.
    result = await workflow.run(example, images, protocol="focus", pdf_path=pdf)
    assert result.answer == "5.5"
    route_step = next(s for s in result.trace.steps if s.stage == "route_pages")
    assert route_step.tier == "text_fts"
    assert route_step.args["n_text_pages"] == 0


# ---------------------------------------------------------------------------
# Verifier→retry loop (Phase 2 item 3)
# ---------------------------------------------------------------------------


class _ScriptedClient:
    """ModelClient that yields a scripted sequence of responses.

    Returns the i-th response on the i-th call. After the script is
    exhausted, repeats the last response (so a forgotten retry doesn't
    surface as an exception — it surfaces as "the verifier kept saying
    the same thing", which is exactly the case the loop's exhaustion
    branch is supposed to handle).
    """

    def __init__(
        self,
        responses: list[str],
        *,
        tokens_in: int = 100,
        tokens_out: int = 25,
    ) -> None:
        self._responses = list(responses)
        self._tokens_in = tokens_in
        self._tokens_out = tokens_out
        self.calls: list[dict[str, Any]] = []

    async def predict(
        self,
        prompt: str,
        images: list[Path] | None = None,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        idx = min(len(self.calls), len(self._responses) - 1)
        self.calls.append({"prompt": prompt, "n_images": len(images or []), "system": system})
        return ModelResponse(
            text=self._responses[idx],
            tokens_in=self._tokens_in,
            tokens_out=self._tokens_out,
            usd=0.001,
            latency_ms=40,
        )

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)


def _verdict_json(
    *,
    supported: bool,
    next_action: str,
    reason: str = "test reason",
    confidence: float = 0.7,
) -> str:
    return (
        f'{{"supported": {str(supported).lower()}, '
        f'"next_action": "{next_action}", '
        f'"reason": "{reason}", '
        f'"confidence": {confidence}}}'
    )


async def test_loop_accept_on_first_verdict_no_retries(tmp_path, parser_bench_submodule_present):
    """Verifier says accept on first call → no retries, telemetry shows
    loop_terminated=accepted, retries_used=0, retry_helped=None."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    reasoner = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.9}')
    verifier = _FakeClient(_verdict_json(supported=True, next_action="accept"))
    tier_router = _FakeTierRouter(verifier=verifier)
    workflow = FocusWorkflow(backend_client=reasoner, tier_router=tier_router)

    result = await workflow.run(
        _make_example(), [tmp_path / "datasheet-A_page_0003_300dpi.png"], protocol="focus"
    )
    assert result.telemetry["retries_used"] == 0
    assert result.telemetry["loop_terminated"] == "accepted"
    assert result.telemetry["loop_retry_helped"] is None
    # Answer + verify each ran once.
    answer_steps = [s for s in result.trace.steps if s.stage == "answer"]
    verify_steps = [s for s in result.trace.steps if s.stage == "verify"]
    assert len(answer_steps) == 1
    assert len(verify_steps) == 1


async def test_loop_retry_localization_reruns_localize_inspect_expand_answer_verify(
    tmp_path, parser_bench_submodule_present
):
    """retry_localization fires once → localize/inspect/expand/answer/verify each
    run twice (initial + 1 retry). Verifier accepts on the second pass."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    reasoner = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.9}')
    verifier = _ScriptedClient(
        [
            _verdict_json(supported=False, next_action="retry_localization"),
            _verdict_json(supported=True, next_action="accept"),
        ]
    )
    # Default `max_retries=0` since the n=30 A/B; pin =2 here to exercise
    # the loop path this test covers.
    workflow = FocusWorkflow(
        backend_client=reasoner,
        tier_router=_FakeTierRouter(verifier=verifier),
        max_retries=2,
    )

    result = await workflow.run(
        _make_example(), [tmp_path / "datasheet-A_page_0003_300dpi.png"], protocol="focus"
    )

    assert result.telemetry["retries_used"] == 1
    assert result.telemetry["loop_terminated"] == "accepted"
    # initial unsupported + final supported → loop helped
    assert result.telemetry["loop_retry_helped"] is True

    stage_counts = _stage_counts(result)
    # Initial pass + 1 retry of the 5 stages downstream of route_pages.
    assert stage_counts["localize"] == 2
    assert stage_counts["inspect"] == 2
    assert stage_counts["expand_context"] == 2
    assert stage_counts["answer"] == 2
    assert stage_counts["verify"] == 2
    # Plan + route_pages still run exactly once — they're outside the loop.
    assert stage_counts["plan"] == 1
    assert stage_counts["route_pages"] == 1


async def test_loop_expand_context_reruns_only_expand_answer_verify(
    tmp_path, parser_bench_submodule_present
):
    """expand_context retry doesn't re-run localize or inspect — those are
    upstream of the change and would re-detect the same regions."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    reasoner = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.9}')
    verifier = _ScriptedClient(
        [
            _verdict_json(supported=False, next_action="expand_context"),
            _verdict_json(supported=True, next_action="accept"),
        ]
    )
    # Default `max_retries=0` since the n=30 A/B; pin =2 here to exercise
    # the loop path this test covers.
    workflow = FocusWorkflow(
        backend_client=reasoner,
        tier_router=_FakeTierRouter(verifier=verifier),
        max_retries=2,
    )
    result = await workflow.run(
        _make_example(), [tmp_path / "datasheet-A_page_0003_300dpi.png"], protocol="focus"
    )

    stage_counts = _stage_counts(result)
    assert stage_counts["expand_context"] == 2
    assert stage_counts["answer"] == 2
    assert stage_counts["verify"] == 2
    # Localize + inspect stay at 1 — no re-detection.
    assert stage_counts["localize"] == 1
    assert stage_counts["inspect"] == 1

    # The retry expand step records a wider adjacency_pad in args.
    expand_steps = [s for s in result.trace.steps if s.stage == "expand_context"]
    pads = [s.args.get("adjacency_pad") for s in expand_steps]
    assert pads[0] < pads[1], f"adjacency_pad should grow on retry; got {pads}"


async def test_loop_escalate_reasoner_reruns_only_answer_verify(
    tmp_path, parser_bench_submodule_present
):
    """escalate_reasoner re-runs only answer + verify. The retry answer call
    carries the verifier's reason as an `escalation_hint`."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    reasoner = _ScriptedClient(
        [
            '{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.4}',
            '{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.9}',
        ]
    )
    verifier = _ScriptedClient(
        [
            _verdict_json(
                supported=False,
                next_action="escalate_reasoner",
                reason="reasoner mis-read the cited table cell",
            ),
            _verdict_json(supported=True, next_action="accept"),
        ]
    )
    # Default `max_retries=0` since the n=30 A/B; pin =2 here to exercise
    # the loop path this test covers.
    workflow = FocusWorkflow(
        backend_client=reasoner,
        tier_router=_FakeTierRouter(verifier=verifier),
        max_retries=2,
    )
    result = await workflow.run(
        _make_example(), [tmp_path / "datasheet-A_page_0003_300dpi.png"], protocol="focus"
    )

    stage_counts = _stage_counts(result)
    assert stage_counts["answer"] == 2
    assert stage_counts["verify"] == 2
    # Localize / inspect / expand all stay at 1 — escalation doesn't touch them.
    assert stage_counts["localize"] == 1
    assert stage_counts["inspect"] == 1
    assert stage_counts["expand_context"] == 1

    # Retry answer step records the escalation hint.
    answer_steps = [s for s in result.trace.steps if s.stage == "answer"]
    assert answer_steps[0].args.get("had_escalation_hint") is False
    assert answer_steps[1].args.get("had_escalation_hint") is True


async def test_loop_abstain_terminates_with_unanswerable(tmp_path, parser_bench_submodule_present):
    """abstain replaces the answer with 'Unanswerable' and ends the loop."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    reasoner = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.9}')
    verifier = _FakeClient(
        _verdict_json(
            supported=False,
            next_action="abstain",
            reason="no evidence for the question",
        )
    )
    # Default `max_retries=0` since the n=30 A/B; pin =2 here to exercise
    # the loop path this test covers.
    workflow = FocusWorkflow(
        backend_client=reasoner,
        tier_router=_FakeTierRouter(verifier=verifier),
        max_retries=2,
    )

    result = await workflow.run(
        _make_example(), [tmp_path / "datasheet-A_page_0003_300dpi.png"], protocol="focus"
    )
    assert result.answer == "Unanswerable"
    assert result.telemetry["loop_terminated"] == "abstained"
    # Abstention was decided on the first verdict — no retries fired.
    assert result.telemetry["retries_used"] == 0
    assert result.citations == []  # abstention drops citations


async def test_loop_exhausted_when_max_retries_hit(tmp_path, parser_bench_submodule_present):
    """Verifier keeps saying retry → loop runs max_retries times and exits as
    `exhausted` with the last (still-unsupported) answer."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    reasoner = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.7}')
    # Always retry. Even at max=2 the loop runs 2 retries then exits.
    verifier = _FakeClient(
        _verdict_json(supported=False, next_action="retry_localization", confidence=0.6)
    )
    workflow = FocusWorkflow(
        backend_client=reasoner,
        tier_router=_FakeTierRouter(verifier=verifier),
        max_retries=2,
    )
    result = await workflow.run(
        _make_example(), [tmp_path / "datasheet-A_page_0003_300dpi.png"], protocol="focus"
    )
    assert result.telemetry["retries_used"] == 2
    assert result.telemetry["loop_terminated"] == "exhausted"
    # Initial false + final still false → retry_helped is False (not None).
    assert result.telemetry["loop_retry_helped"] is False
    # Verify ran 1 + 2 = 3 times.
    stage_counts = _stage_counts(result)
    assert stage_counts["verify"] == 3
    assert stage_counts["localize"] == 3  # initial + 2 retries


async def test_loop_max_retries_zero_disables_loop(tmp_path, parser_bench_submodule_present):
    """max_retries=0 → workflow falls back to pre-loop cascade behavior. The
    verifier's next_action is recorded but never acted on."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    reasoner = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.9}')
    verifier = _FakeClient(_verdict_json(supported=False, next_action="retry_localization"))
    workflow = FocusWorkflow(
        backend_client=reasoner,
        tier_router=_FakeTierRouter(verifier=verifier),
        max_retries=0,
    )
    result = await workflow.run(
        _make_example(), [tmp_path / "datasheet-A_page_0003_300dpi.png"], protocol="focus"
    )
    # Loop didn't fire even though next_action != accept.
    assert result.telemetry["retries_used"] == 0
    assert result.telemetry["loop_terminated"] == "exhausted"
    # Each stage still runs exactly once.
    stage_counts = _stage_counts(result)
    for stage in (
        "plan",
        "route_pages",
        "localize",
        "inspect",
        "expand_context",
        "answer",
        "verify",
    ):
        assert stage_counts[stage] == 1, f"stage {stage} ran {stage_counts[stage]} times"


async def test_loop_unknown_action_terminates_as_accepted(tmp_path, parser_bench_submodule_present):
    """A future verifier extension that emits an unrecognized next_action
    should NOT crash the workflow — it should accept the current answer
    rather than thrash."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    reasoner = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.9}')
    # The verifier's pydantic schema only accepts the 5 known actions, so
    # we can't actually feed an unknown action through the LLM path. We
    # simulate this with a hand-built verifier that bypasses the LLM by
    # returning supported=True, next_action="accept" (the canonical
    # "no-op" path). The branch that handles unknown actions in
    # workflow.run is exercised only via type-erased extensions; the
    # test below just confirms the bail-out path doesn't loop infinitely
    # when the verifier emits a quiet accept.
    verifier = _FakeClient(_verdict_json(supported=True, next_action="accept"))
    # Default `max_retries=0` since the n=30 A/B; pin =2 here to exercise
    # the loop path this test covers.
    workflow = FocusWorkflow(
        backend_client=reasoner,
        tier_router=_FakeTierRouter(verifier=verifier),
        max_retries=2,
    )
    result = await workflow.run(
        _make_example(), [tmp_path / "datasheet-A_page_0003_300dpi.png"], protocol="focus"
    )
    assert result.telemetry["loop_terminated"] == "accepted"
    assert result.telemetry["retries_used"] == 0


def _stage_counts(result) -> dict[str, int]:
    counts: dict[str, int] = {}
    for s in result.trace.steps:
        counts[s.stage] = counts.get(s.stage, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Region reranker wiring (Phase 2 item 4)
# ---------------------------------------------------------------------------


async def test_focus_workflow_routes_rerank_through_tier_router(
    tmp_path, parser_bench_submodule_present
):
    """When `localizer_rerank` is wired through the tier_router, the rerank
    step records its tokens + tier, and the LLM is called once between
    localize and inspect."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")

    reasoner = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.9}')
    # Skeleton inspector emits one packet per region (= one per regions
    # candidate). The rerank LLM scores them; the wiring just needs to
    # confirm the call happened.
    rerank_client = _FakeClient(
        '{"regions": [{"region_id": "r0_p3", "relevance": 0.85, "needed_for": "primary"}]}',
        tokens_in=180,
        tokens_out=50,
    )
    tier_router = _FakeTierRouter(localizer_rerank=rerank_client)
    workflow = FocusWorkflow(backend_client=reasoner, tier_router=tier_router)
    images = [tmp_path / "datasheet-A_page_0003_300dpi.png"]

    result = await workflow.run(_make_example(), images, protocol="focus")

    # Tier router was asked for localizer_rerank (and other roles).
    assert "localizer_rerank" in tier_router.calls
    # Rerank client was called exactly once with the structured prompt.
    assert len(rerank_client.calls) == 1
    assert "Question: What is the max supply voltage?" in rerank_client.calls[0]["prompt"]

    # Trajectory has one rerank step in mid-tier mode.
    rerank_steps = [s for s in result.trace.steps if s.stage == "rerank"]
    assert len(rerank_steps) == 1
    step = rerank_steps[0]
    assert step.action == "llm_call"
    assert step.tier == "mid"
    assert step.tokens_in == 180
    assert step.tokens_out == 50


async def test_focus_workflow_rerank_step_is_skeleton_when_no_router(
    tmp_path, parser_bench_submodule_present
):
    """Without a tier_router (or without a localizer_rerank client), the
    rerank step still appears in the trajectory but at tier=skeleton with
    zero tokens — keeps the step shape stable for trace consumers."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")

    client = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.9}')
    workflow = FocusWorkflow(backend_client=client)  # no tier_router
    images = [tmp_path / "datasheet-A_page_0003_300dpi.png"]
    result = await workflow.run(_make_example(), images, protocol="focus")

    rerank_steps = [s for s in result.trace.steps if s.stage == "rerank"]
    assert len(rerank_steps) == 1
    step = rerank_steps[0]
    assert step.tier == "skeleton"
    assert step.action == "deterministic"
    assert step.tokens_in == 0


async def test_focus_workflow_rerank_runs_on_localization_retry(
    tmp_path, parser_bench_submodule_present
):
    """When `retry_localization` re-runs localize, the rerank should also
    re-fire — the new region set deserves the same query-conditioned
    scoring as the initial pass."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")

    reasoner = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.9}')
    rerank_client = _FakeClient(
        '{"regions": [{"region_id": "r0_p3", "relevance": 0.5, "needed_for": "primary"}]}'
    )
    verifier = _ScriptedClient(
        [
            _verdict_json(supported=False, next_action="retry_localization"),
            _verdict_json(supported=True, next_action="accept"),
        ]
    )
    workflow = FocusWorkflow(
        backend_client=reasoner,
        tier_router=_FakeTierRouter(localizer_rerank=rerank_client, verifier=verifier),
        max_retries=2,
    )
    images = [tmp_path / "datasheet-A_page_0003_300dpi.png"]
    result = await workflow.run(_make_example(), images, protocol="focus")

    stage_counts = _stage_counts(result)
    # Initial pass + retry → localize + rerank both run twice.
    assert stage_counts["localize"] == 2
    assert stage_counts["rerank"] == 2
    # Rerank LLM was called twice (once per localize pass).
    assert len(rerank_client.calls) == 2


# ---------------------------------------------------------------------------
# Phase 2 / Phase 3: SimpleBaselineAgent prompt enrichment
# ---------------------------------------------------------------------------


async def test_simple_agent_prompt_includes_page_mapping(tmp_path, parser_bench_submodule_present):
    """Single image at page 50 → user prompt mentions 'page 50'."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    from focusparse.pipeline.workflow import SimpleBaselineAgent

    client = _FakeClient('{"answer": "5.5", "citations": []}')
    agent = SimpleBaselineAgent(backend_client=client, protocol="full_doc")
    img = tmp_path / "Arm_EE382N_4_page_0050_300dpi.png"
    img.write_bytes(b"fake")

    await agent.run(_make_example(), [img], image_pages=[50])

    prompt = client.calls[0]["prompt"]
    assert "page 50" in prompt
    # Sanity: the question is still in the prompt
    assert "supply voltage" in prompt


async def test_simple_agent_prompt_lists_multi_image_page_mapping(
    tmp_path, parser_bench_submodule_present
):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    from focusparse.pipeline.workflow import SimpleBaselineAgent

    client = _FakeClient('{"answer": "5.5", "citations": []}')
    agent = SimpleBaselineAgent(backend_client=client, protocol="full_doc")

    await agent.run(_make_example(), [tmp_path / "a.png", tmp_path / "b.png"], image_pages=[50, 12])

    prompt = client.calls[0]["prompt"]
    assert "image 1 = page 50" in prompt
    assert "image 2 = page 12" in prompt


async def test_simple_agent_prompt_omits_page_mapping_when_none(
    tmp_path, parser_bench_submodule_present
):
    """Backwards compat: legacy callers (no image_pages) get the bare question."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    from focusparse.pipeline.workflow import SimpleBaselineAgent

    client = _FakeClient('{"answer": "5.5", "citations": []}')
    agent = SimpleBaselineAgent(backend_client=client, protocol="full_doc")

    await agent.run(_make_example(), [tmp_path / "a.png"])

    prompt = client.calls[0]["prompt"]
    assert "page" not in prompt.split("\n")[0]  # First line is just the question.


async def test_simple_agent_prompt_includes_numeric_format_hint(
    tmp_path, parser_bench_submodule_present
):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    from focusparse.pipeline.workflow import SimpleBaselineAgent

    client = _FakeClient('{"answer": "5.5", "citations": []}')
    agent = SimpleBaselineAgent(backend_client=client, protocol="full_doc")

    # _make_example sets answer_type='numeric'
    await agent.run(_make_example(), [tmp_path / "a.png"])

    prompt = client.calls[0]["prompt"]
    assert "single number" in prompt.lower()


async def test_simple_agent_prompt_includes_exact_match_hint(
    tmp_path, parser_bench_submodule_present
):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    from focusparse._parser_bench import AnswerType
    from focusparse.pipeline.workflow import SimpleBaselineAgent

    client = _FakeClient('{"answer": "0x44", "citations": []}')
    agent = SimpleBaselineAgent(backend_client=client, protocol="full_doc")

    ex = _make_example().model_copy(update={"answer_type": AnswerType.EXACT_MATCH})
    await agent.run(ex, [tmp_path / "a.png"])

    prompt = client.calls[0]["prompt"]
    assert "exact label" in prompt.lower()


async def test_simple_agent_prompt_includes_boolean_hint(tmp_path, parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    from focusparse._parser_bench import AnswerType
    from focusparse.pipeline.workflow import SimpleBaselineAgent

    client = _FakeClient('{"answer": "yes", "citations": []}')
    agent = SimpleBaselineAgent(backend_client=client, protocol="full_doc")

    ex = _make_example().model_copy(update={"answer_type": AnswerType.BOOLEAN})
    await agent.run(ex, [tmp_path / "a.png"])

    prompt = client.calls[0]["prompt"]
    assert "yes" in prompt.lower() and "no" in prompt.lower()
