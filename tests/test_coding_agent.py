"""Tests for the coding-agent comparator.

Pure mock-driven except for the standard harness scoring path; no real LLM,
layout endpoint, or PDF tooling is called.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from focusparse.models.base import ModelResponse
from focusparse.pipeline.coding_agent import (
    CodingAgent,
    coding_agent_tools,
    run_coding_agent_eval,
)
from focusparse.tools import (
    GET_TEXT_LAYER_SPEC,
    INSPECT_REGION_SPEC,
    LAYOUT_DETECT_SPEC,
    RUN_PYTHON_SPEC,
    ToolSpec,
    resolve_tool_set,
)


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
        return ModelResponse(text=text, tokens_in=100, tokens_out=12, usd=0.001, latency_ms=50)

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)


def _example(example_id: str = "ex-code"):
    from focusparse._parser_bench import BBox, BenchmarkExample

    return BenchmarkExample(
        id=example_id,
        domain="datasheet",
        source_pdf="datasheet-A.pdf",
        page_images=[f"images/{example_id}_page_0003_300dpi.png"],
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


def _loose_example(example_id: str = "ex-code") -> SimpleNamespace:
    return SimpleNamespace(
        id=example_id,
        question="What is the max supply voltage?",
        domain="datasheet",
        source_pdf="datasheet-A.pdf",
        page_images=[f"images/{example_id}_page_0003_300dpi.png"],
        supporting_pages=[3],
    )


def _stub_tool_spec(name: str) -> ToolSpec:
    from pydantic import BaseModel

    class _StubInput(BaseModel):
        echo: str = ""

    async def _runner(inp: _StubInput, **_kw: Any) -> dict[str, Any]:
        return {"echoed": inp.echo}

    return ToolSpec(
        name=name,
        description=f"{name} stub for tests",
        input_model=_StubInput,
        runner=_runner,
        summarize=lambda out: f"echoed={out.get('echoed')}",
    )


def _stub_full_tools() -> list[ToolSpec]:
    return [
        _stub_tool_spec("inspect_region"),
        _stub_tool_spec("get_text_layer"),
        _stub_tool_spec("layout_detect"),
        _stub_tool_spec("run_python"),
    ]


def test_coding_agent_tool_belt_is_fixed_full_plus_four() -> None:
    tools = coding_agent_tools()
    assert [t.name for t in tools] == [
        INSPECT_REGION_SPEC.name,
        GET_TEXT_LAYER_SPEC.name,
        LAYOUT_DETECT_SPEC.name,
        RUN_PYTHON_SPEC.name,
    ]


def test_coding_agent_rejects_minimal_tool_belt() -> None:
    client = _ScriptedClient(['{"final_answer": "5.5", "citations": []}'])
    with pytest.raises(ValueError, match="full \\+4 tool belt"):
        CodingAgent(backend_client=client, tools=resolve_tool_set("minimal"))


async def test_coding_agent_prompt_encourages_run_python() -> None:
    client = _ScriptedClient(['{"thought": "done", "final_answer": "5.5", "citations": []}'])
    agent = CodingAgent(backend_client=client, tools=_stub_full_tools())
    await agent.run(_loose_example(), images=[])

    system = client.calls[0]["system"]
    assert "think-act-observe" in system
    assert "Use the full +4 tool belt" in system
    assert "run_python" in system
    assert "zooming, annotation, counting" in system
    assert "cite observed evidence" in system


async def test_coding_agent_dispatches_code_tool_and_marks_trace() -> None:
    client = _ScriptedClient(
        [
            '{"thought": "compute", "action": "run_python", "action_input": {"echo": "counted"}}',
            '{"thought": "observed", "final_answer": "5.5", '
            '"citations": [{"page": 3, "bbox": [0.1, 0.2, 0.3, 0.4]}]}',
        ]
    )
    agent = CodingAgent(backend_client=client, tools=_stub_full_tools())
    result = await agent.run(_loose_example(), images=[])

    assert result.answer == "5.5"
    assert result.telemetry["n_tool_calls"] == 1
    assert "echoed=counted" in client.calls[1]["prompt"]
    assert result.trace.plan["agent"] == "coding_agent"
    assert [step.stage for step in result.trace.steps] == [
        "coding_agent_step",
        "coding_agent_final",
    ]
    assert result.trace.steps[0].tool == "run_python"


async def test_run_coding_agent_eval_writes_standard_artifacts(
    tmp_path,
    parser_bench_submodule_present,
) -> None:
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")

    example = _example("ex-eval")
    image_path = tmp_path / "images" / "ex-eval_page_0003_300dpi.png"
    image_path.parent.mkdir(parents=True)
    Image.new("RGB", (800, 600), color=(255, 255, 255)).save(image_path)

    client = _ScriptedClient(
        [
            '{"thought": "observed", "final_answer": "5.5", '
            '"citations": [{"page": 3, "bbox": [0.1, 0.2, 0.3, 0.4]}]}'
        ]
    )
    run_dir = tmp_path / "run"
    result = await run_coding_agent_eval(
        [example],
        backend_client=client,
        backend="fake",
        model="fake-1",
        protocol="full_doc",
        output_dir=run_dir,
        images_root=tmp_path,
        limit=1,
    )

    assert result["aggregate"].n == 1
    assert result["per_example"][0]["answer_correct"] == 1.0
    assert result["per_example"][0]["available_tools"] == [
        "inspect_region",
        "get_text_layer",
        "layout_detect",
        "run_python",
    ]

    manifest = json.loads((run_dir / "run.json").read_text())
    assert manifest["agent"] == "coding_agent"
    assert manifest["tool_set"] == "full"
    assert manifest["available_tools"] == [
        "inspect_region",
        "get_text_layer",
        "layout_detect",
        "run_python",
    ]

    rows = (run_dir / "per_example.jsonl").read_text().strip().splitlines()
    assert len(rows) == 1
    assert (run_dir / "predictions" / "ex-eval.json").is_file()


async def test_run_coding_agent_eval_minimal_artifacts_skip_prediction_cache(
    tmp_path,
    parser_bench_submodule_present,
) -> None:
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")

    example = _example("ex-minimal")
    image_path = tmp_path / "images" / "ex-minimal_page_0003_300dpi.png"
    image_path.parent.mkdir(parents=True)
    Image.new("RGB", (800, 600), color=(255, 255, 255)).save(image_path)

    client = _ScriptedClient(
        [
            '{"thought": "observed", "final_answer": "5.5", '
            '"citations": [{"page": 3, "bbox": [0.1, 0.2, 0.3, 0.4]}]}'
        ]
    )
    run_dir = tmp_path / "minimal-run"
    result = await run_coding_agent_eval(
        [example],
        backend_client=client,
        backend="fake",
        model="fake-1",
        protocol="full_doc",
        output_dir=run_dir,
        images_root=tmp_path,
        limit=1,
        write_prediction_cache=False,
        persist_intermediate_artifacts=False,
    )

    assert result["aggregate"].n == 1
    manifest = json.loads((run_dir / "run.json").read_text())
    assert manifest["artifact_policy"] == {
        "write_prediction_cache": False,
        "persist_intermediate_artifacts": False,
    }
    assert (run_dir / "per_example.jsonl").is_file()
    assert not (run_dir / "predictions").exists()
