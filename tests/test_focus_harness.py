"""Tests for `focusparse.eval.harness.run_focus_eval`.

Mirrors `tests/test_harness.py` — fake client, in-memory examples, gated on
the parser-bench submodule. These verify the harness correctly:
  - constructs `FocusWorkflow` per call and drives it on every example
  - records "agent": "focus" in the manifest
  - populates per-example focus columns (tool_calls, is_lazy) from the trace
  - caches predictions and honors resume
  - survives a backend error without poisoning the run
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from focusparse.eval.harness import run_focus_eval
from focusparse.models.base import ModelResponse


class _FakeClient:
    def __init__(self, response_text: str) -> None:
        self._text = response_text
        self.calls = 0

    async def predict(
        self,
        prompt: str,
        images: list[Path] | None = None,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        self.calls += 1
        return ModelResponse(
            text=self._text,
            tokens_in=120,
            tokens_out=20,
            usd=0.0015,
            latency_ms=60,
        )

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)


def _make_example(example_id: str, answer: str = "5.5"):
    from focusparse._parser_bench import BBox, BenchmarkExample

    return BenchmarkExample(
        id=example_id,
        domain="datasheet",
        source_pdf="datasheet-A.pdf",
        page_images=[f"images/{example_id}_page_0003_300dpi.png"],
        question="What is the max supply voltage?",
        answer=answer,
        answer_type="numeric",
        answer_unit="V",
        tolerance=0.01,
        supporting_pages=[3],
        supporting_bboxes=[BBox(page=3, x0=0.0, y0=0.0, x1=1.0, y1=1.0)],
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


# ---------------------------------------------------------------------------
# End-to-end
# ---------------------------------------------------------------------------


async def test_run_focus_eval_scores_correct_answer(tmp_path, parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")

    # Reasoner emits a packet_id citation — skeleton inspector always names
    # its first region pkt_000, so "pkt_000" resolves cleanly.
    client = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.9}')
    examples = [_make_example("ex-a"), _make_example("ex-b")]

    result = await run_focus_eval(
        examples,
        backend_client=client,
        backend="fake",
        model="fake-1",
        protocol="focus_default",
        output_dir=tmp_path / "run",
        images_root=tmp_path,
        limit=2,
    )

    agg = result["aggregate"]
    assert agg.n == 2
    # Both answers match gold → accuracy = 1.0
    assert agg.accuracy == 1.0
    # USD aggregates two reasoner calls
    assert agg.usd_total == pytest.approx(0.003)
    # One real tool_call recorded per run (skeleton_inspector) + one llm_call
    # at the answer step. The harness counts both.
    assert agg.tool_calls_mean >= 1.0

    # Manifest shape
    manifest = json.loads((tmp_path / "run" / "run.json").read_text())
    assert manifest["agent"] == "focus"
    assert manifest["backend"] == "fake"
    assert manifest["protocol"] == "focus_default"
    assert manifest["n_examples"] == 2


async def test_run_focus_eval_records_focus_metrics(tmp_path, parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")

    # Valid packet_id → non-lazy row (has citation + tool_call).
    client = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.8}')
    examples = [_make_example("ex-a")]
    result = await run_focus_eval(
        examples,
        backend_client=client,
        backend="fake",
        model="fake-1",
        protocol="focus_default",
        output_dir=tmp_path / "run",
        images_root=tmp_path,
        limit=1,
    )
    per = result["per_example"][0]
    # Citations translated back to {page, bbox} — not empty
    assert per["citations"]
    assert per["tool_calls"] >= 1
    # Not lazy because we have tool calls AND predicted bboxes
    assert per["is_lazy"] == 0


async def test_run_focus_eval_flags_lazy_when_no_citations(
    tmp_path, parser_bench_submodule_present
):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")

    # Reasoner refuses to cite → lazy row regardless of answer correctness.
    client = _FakeClient('{"answer": "5.5", "citations": [], "confidence": 0.1}')
    result = await run_focus_eval(
        [_make_example("ex-lazy")],
        backend_client=client,
        backend="fake",
        model="fake-1",
        protocol="focus_default",
        output_dir=tmp_path / "run",
        images_root=tmp_path,
        limit=1,
    )
    per = result["per_example"][0]
    assert per["is_lazy"] == 1
    # evidence_reward is zeroed by the lazy-penalty path
    assert per["evidence_reward"] == 0.0


async def test_run_focus_eval_resume_hits_cache(tmp_path, parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")

    client = _FakeClient('{"answer": "5.5", "citations": [], "confidence": 0.1}')
    examples = [_make_example("ex-a"), _make_example("ex-b")]

    run_dir = tmp_path / "run"
    await run_focus_eval(
        examples,
        backend_client=client,
        backend="fake",
        model="fake-1",
        protocol="focus_default",
        output_dir=run_dir,
        images_root=tmp_path,
        limit=2,
    )
    first_calls = client.calls
    assert first_calls == 2  # one reasoner call per example

    # Same output_dir → cache hit, no new calls.
    await run_focus_eval(
        [_make_example("ex-a"), _make_example("ex-b")],
        backend_client=client,
        backend="fake",
        model="fake-1",
        protocol="focus_default",
        output_dir=run_dir,
        images_root=tmp_path,
        limit=2,
        resume=True,
    )
    assert client.calls == first_calls


async def test_run_focus_eval_handles_backend_error(tmp_path, parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")

    class _BrokenClient:
        async def predict(self, *a: Any, **kw: Any) -> ModelResponse:
            raise RuntimeError("simulated provider outage")

        def count_tokens(self, text: str) -> int:
            return 1

    result = await run_focus_eval(
        [_make_example("ex-err")],
        backend_client=_BrokenClient(),
        backend="fake",
        model="fake-1",
        protocol="focus_default",
        output_dir=tmp_path / "run",
        images_root=tmp_path,
        limit=1,
    )
    agg = result["aggregate"]
    assert agg.n == 1
    assert agg.accuracy == 0.0
    per = result["per_example"][0]
    assert per["error"].startswith("simulated")


# ---------------------------------------------------------------------------
# pdf_path resolution (sub-phase 2f end-to-end)
# ---------------------------------------------------------------------------


def _write_tiny_pdf(path: Path, pages_text: dict[int, str]) -> Path:
    import fitz

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    for page_idx in sorted(pages_text):
        page = doc.new_page(width=600, height=800)
        page.insert_text((50, 50), pages_text[page_idx], fontsize=12)
    doc.save(path)
    doc.close()
    return path


async def test_run_focus_eval_threads_pdf_path_when_file_present(
    tmp_path, parser_bench_submodule_present
):
    """With pdfs_root and a real PDF, the route_pages step upgrades to
    tier=text_fts and n_text_pages > 0."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")

    pdfs_root = tmp_path / "pdfs"
    _write_tiny_pdf(
        pdfs_root / "datasheet-A.pdf",
        pages_text={1: "filler", 2: "filler", 3: "VCC maximum supply voltage rating"},
    )

    client = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.9}')
    result = await run_focus_eval(
        [_make_example("ex-pdf")],
        backend_client=client,
        backend="fake",
        model="fake-1",
        protocol="focus_default",
        output_dir=tmp_path / "run",
        images_root=tmp_path,
        limit=1,
        pdfs_root=pdfs_root,
    )
    # Cached per-example payload should still parse; the trace isn't in the
    # aggregate return, but the run completes (that's the main regression
    # guard here). A deeper check on the tier="text_fts" path lives in
    # tests/test_workflow.py where the workflow is instantiated directly.
    assert result["aggregate"].n == 1


async def test_run_focus_eval_falls_back_when_pdf_missing(tmp_path, parser_bench_submodule_present):
    """pdfs_root set but the specific PDF is missing → skeleton router,
    run still completes (no crash)."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")

    # pdfs_root exists but contains nothing for the example's source_pdf.
    pdfs_root = tmp_path / "pdfs"
    pdfs_root.mkdir()

    client = _FakeClient('{"answer": "5.5", "citations": ["pkt_000"], "confidence": 0.8}')
    result = await run_focus_eval(
        [_make_example("ex-nopdf")],
        backend_client=client,
        backend="fake",
        model="fake-1",
        protocol="focus_default",
        output_dir=tmp_path / "run",
        images_root=tmp_path,
        limit=1,
        pdfs_root=pdfs_root,
    )
    assert result["aggregate"].n == 1


async def test_resolve_pdf_path_tries_nested_layout(tmp_path):
    """parser-bench sometimes nests PDFs as <root>/<doc_stem>/<doc>.pdf."""
    from focusparse._parser_bench import BBox, BenchmarkExample
    from focusparse.eval.harness import _resolve_pdf_path

    pdfs_root = tmp_path / "pdfs"
    nested = pdfs_root / "doc-nested" / "doc-nested.pdf"
    nested.parent.mkdir(parents=True)
    nested.write_bytes(b"%PDF-1.4\n")

    example = BenchmarkExample(
        id="ex-nested",
        domain="datasheet",
        source_pdf="doc-nested.pdf",
        page_images=[],
        question="q?",
        answer="x",
        answer_type="exact_match",
        supporting_pages=[1],
        supporting_bboxes=[BBox(page=1, x0=0, y0=0, x1=1, y1=1)],
        alternate_bboxes=[],
        evidence_relations=[],
        multi_region_required=False,
        requires_visual=False,
        difficulty={"visual": 1, "reasoning": 1, "localization": 1},
        question_family="single_value_lookup",
        stress_type="none",
        reasoning_chain=None,
        evidence_page_spread=0,
        adversarial_type=None,
        split="dev",
        original_bboxes=[],
    )
    resolved = _resolve_pdf_path(pdfs_root, example)
    assert resolved == nested


def test_resolve_pdf_path_returns_none_when_root_is_none(tmp_path):
    from focusparse._parser_bench import BBox, BenchmarkExample
    from focusparse.eval.harness import _resolve_pdf_path

    example = BenchmarkExample(
        id="ex-none",
        domain="datasheet",
        source_pdf="anything.pdf",
        page_images=[],
        question="q?",
        answer="x",
        answer_type="exact_match",
        supporting_pages=[1],
        supporting_bboxes=[BBox(page=1, x0=0, y0=0, x1=1, y1=1)],
        alternate_bboxes=[],
        evidence_relations=[],
        multi_region_required=False,
        requires_visual=False,
        difficulty={"visual": 1, "reasoning": 1, "localization": 1},
        question_family="single_value_lookup",
        stress_type="none",
        reasoning_chain=None,
        evidence_page_spread=0,
        adversarial_type=None,
        split="dev",
        original_bboxes=[],
    )
    assert _resolve_pdf_path(None, example) is None
