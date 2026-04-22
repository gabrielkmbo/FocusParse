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
    # region, which the skeleton router maps to page 1 (positional, since the
    # filename-parsed page 3 is still the real page).
    assert len(result.citations) == 1
    assert "page" in result.citations[0]
    assert "bbox" in result.citations[0]
    assert result.citations[0]["bbox"] == [0.0, 0.0, 1.0, 1.0]

    # Seven recorded steps, one per @step (plan, route_pages, localize,
    # inspect, expand_context, answer, verify).
    stages = [step.stage for step in result.trace.steps]
    assert stages == [
        "plan",
        "route_pages",
        "localize",
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
    assert len(result.trace.steps) == 7


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
    assert len(result.trace.steps) == 7
    # Reasoner got called with zero images (packet list empty).
    assert len(client.calls) == 1
    assert client.calls[0]["n_images"] == 0
