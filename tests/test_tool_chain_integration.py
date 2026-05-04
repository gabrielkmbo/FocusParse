"""Integration smoke: layout_detect → inspect_region chain.

Walks the most failure-prone leg of the tool chain end-to-end with a
scripted-mock LLM. The pixel→norm conversion contract (documented in
DetectedBox.bbox.description) is the silent footgun that broke chains
in headline-v1; this test fires if any future docstring change
de-syncs the conversion rule from the runtime requirement.

The run_python leg of the chain is covered separately in
`tests/test_run_python.py::test_image_refs_accept_absolute_path_input`
(absolute-path crop_refs become sandbox dict keys identically).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from focusparse.models.base import ModelResponse
from focusparse.pipeline.react_agent import ReActAgent
from focusparse.tools import (
    GET_TEXT_LAYER_SPEC,
    INSPECT_REGION_SPEC,
    LAYOUT_DETECT_SPEC,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_pdf(path: Path) -> Path:
    """Tiny synthetic PDF with a chart-like region."""
    import fitz

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((50, 80), "Datasheet — Memory Stack Usage", fontsize=14)
    page.insert_text((50, 200), "Figure 1: Stack frame layout", fontsize=10)
    page.draw_rect(fitz.Rect(50, 220, 350, 420), color=(0, 0, 0), width=2)
    doc.save(path)
    doc.close()
    return path


def _render_page_png(pdf_path: Path, png_path: Path, dpi: int = 150) -> tuple[int, int]:
    import fitz

    with fitz.open(pdf_path) as doc:
        page = doc[0]
        zoom = dpi / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        png_path.parent.mkdir(parents=True, exist_ok=True)
        pix.save(png_path)
        return pix.width, pix.height


class _ScriptedClient:
    def __init__(self, scripted_texts: list[str]) -> None:
        self._scripted = list(scripted_texts)
        self.calls: list[dict[str, Any]] = []

    async def predict(
        self,
        prompt: str,
        images: list[Path] | None = None,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        idx = len(self.calls)
        self.calls.append({"prompt": prompt, "images": images, "system": system})
        text = self._scripted[idx] if idx < len(self._scripted) else self._scripted[-1]
        return ModelResponse(text=text, tokens_in=100, tokens_out=10, usd=0.001, latency_ms=50)

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)


def _example():
    from focusparse._parser_bench import (
        AnswerType,
        BBox,
        BenchmarkExample,
        DifficultyScores,
        Domain,
    )

    return BenchmarkExample(
        id="ex-chain",
        domain=Domain.DATASHEET,
        source_pdf="fake.pdf",
        page_images=["page_0001.png"],
        question="What is in the chart on page 1?",
        answer="memory stack",
        answer_type=AnswerType.EXACT_MATCH,
        tolerance=0.5,
        supporting_pages=[1],
        supporting_bboxes=[BBox(page=1, x0=0, y0=0, x1=1, y1=1)],
        difficulty=DifficultyScores(visual=1, reasoning=1, localization=1),
        question_family="single_value_lookup",
    )


# ---------------------------------------------------------------------------
# The integration smoke
# ---------------------------------------------------------------------------


async def test_layout_detect_to_inspect_region_chain(
    parser_bench_submodule_present, tmp_path, monkeypatch
):
    """Walk layout_detect → inspect_region with a scripted LLM.

    Sequence:
      1. layout_detect on the page PNG → returns 2 boxes (pixel space).
      2. inspect_region (mode='image') with bbox_norm derived from box[0]
         (pixel→norm conversion happens at the LLM-script boundary). →
         returns crop_ref to a real cached PNG.
      3. final_answer with a citation pointing at the chart region.

    Asserts: 0 tool_error steps; both tool_call observations are populated;
    inspect_region's crop_ref points at an existing PNG.
    """
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")

    pdf = _write_pdf(tmp_path / "doc.pdf")
    page_png = tmp_path / "pages" / "doc_page_0001_300dpi.png"
    page_w, page_h = _render_page_png(pdf, page_png, dpi=150)

    canned_payload = {
        "pred_boxes": [
            [100.0, 440.0, 700.0, 840.0],
            [100.0, 100.0, 700.0, 200.0],
        ],
        "pred_labels": ["picture", "section_header"],
        "scores": [0.91, 0.85],
        "figure_classifications": {"0": {"figure_class": "bar_chart"}},
    }

    async def _stub_post(**kwargs):
        return canned_payload

    monkeypatch.setattr("focusparse.tools.layout_detect._post_with_retry", _stub_post)
    monkeypatch.setenv("HF_TOKEN", "test-token-not-real")

    bbox_norm = [
        100 / page_w,
        440 / page_h,
        700 / page_w,
        840 / page_h,
    ]

    turns = [
        json.dumps(
            {
                "thought": "Discover regions on the page.",
                "action": "layout_detect",
                "action_input": {"image_path": str(page_png), "page": 1},
            }
        ),
        json.dumps(
            {
                "thought": "Crop the chart region.",
                "action": "inspect_region",
                "action_input": {
                    "doc_path": str(pdf),
                    "page": 1,
                    "bbox_norm": bbox_norm,
                    "mode": "image",
                },
            }
        ),
        json.dumps(
            {
                "thought": "Answer based on the chart caption.",
                "final_answer": "memory stack",
                "citations": [{"page": 1, "bbox": bbox_norm}],
            }
        ),
    ]

    # Use only the two tools actually exercised here so the prompt stays
    # tight and the agent can't accidentally call run_python.
    tools = [LAYOUT_DETECT_SPEC, INSPECT_REGION_SPEC, GET_TEXT_LAYER_SPEC]
    client = _ScriptedClient(turns)
    agent = ReActAgent(backend_client=client, tools=tools)

    result = await agent.run(
        _example(),
        images=[page_png],
        pdf_path=pdf,
        crop_cache_dir=tmp_path / "crops",
        layout_cache_dir=tmp_path / "layout_cache",
    )

    steps = result.trace.steps

    errors = [s for s in steps if s.action == "tool_error"]
    assert not errors, f"unexpected tool errors: {[s.args for s in errors]}"

    tools_called = [s.tool for s in steps if s.action == "tool_call"]
    assert tools_called == ["layout_detect", "inspect_region"]

    # layout_detect step shows it discovered both regions.
    ld_step = next(s for s in steps if s.tool == "layout_detect")
    assert "n_regions=2" in (ld_step.obs_summary or "")
    assert "picture" in (ld_step.obs_summary or "")

    # inspect_region step's observation includes a crop= ref that points
    # at a real cached PNG on disk.
    ir_step = next(s for s in steps if s.tool == "inspect_region")
    obs = ir_step.obs_summary or ""
    assert "crop=" in obs
    # Pull the path out of the summary and assert it exists.
    crop_token = obs.split("crop=")[1].split(",")[0].strip()
    crop_path = Path(crop_token)
    assert crop_path.is_file()

    # The agent's final answer survived.
    assert result.answer == "memory stack"
    assert result.citations == [{"page": 1, "bbox": bbox_norm}]
